"""
Multi-Task Inference Gradio UI
==============================
Simple web UI for testing the inference server.
"""

import gradio as gr
import requests
import json
from typing import List, Tuple
import time

# Default server URL
DEFAULT_SERVER_URL = "http://localhost:9000"


# Label descriptions for UI (using text instead of emoji for compatibility)
LABEL_INFO = {
    'dangerous_content': {
        'icon': '[DANGER]',
        'description': 'Content that promotes dangerous or illegal activities'
    },
    'hate_speech': {
        'icon': '[HATE]',
        'description': 'Attacks on protected groups based on identity'
    },
    'harassment': {
        'icon': '[HARASS]',
        'description': 'Targeting individuals with abusive behavior'
    },
    'sexually_explicit': {
        'icon': '[NSFW]',
        'description': 'Sexual content or solicitation'
    },
    'toxicity': {
        'icon': '[TOXIC]',
        'description': 'General toxic or rude behavior'
    },
    'severe_toxicity': {
        'icon': '[SEVERE]',
        'description': 'Extremely toxic content'
    },
    'threat': {
        'icon': '[THREAT]',
        'description': 'Threats of violence or harm'
    },
    'insult': {
        'icon': '[INSULT]',
        'description': 'Personal attacks and insults'
    },
    'identity_attack': {
        'icon': '[ID_ATTACK]',
        'description': 'Attacks based on personal characteristics'
    },
    'phish': {
        'icon': '[PHISH]',
        'description': 'Phishing attempts or suspicious links'
    },
    'spam': {
        'icon': '[SPAM]',
        'description': 'Unwanted promotional content or noise'
    }
}


def check_health(server_url: str) -> str:
    """Check server health."""
    try:
        response = requests.get(f"{server_url}/", timeout=5)
        data = response.json()
        return f"OK - Server is healthy\nDevice: {data.get('device', 'unknown')}\nQueue: {data.get('queue_size', 0)}"
    except Exception as e:
        return f"ERROR: {str(e)}"


def predict_single(text: str, threshold: float, server_url: str) -> Tuple[str, str]:
    """Predict a single text."""
    if not text.strip():
        return "Please enter some text", ""
    
    try:
        start = time.time()
        response = requests.post(
            f"{server_url}/predict",
            json={"text": text, "threshold": threshold},
            timeout=30
        )
        elapsed = (time.time() - start) * 1000
        
        if response.status_code != 200:
            return f"ERROR: {response.text}", ""
        
        result = response.json()
        predictions = result['predictions']
        
        # Format output
        output_lines = []
        output_lines.append(f"### Results (inference: {elapsed:.1f}ms)")
        output_lines.append("")
        
        # Detected categories section
        if result['detected_categories']:
            output_lines.append("#### Detected Categories:")
            for cat in result['detected_categories']:
                info = LABEL_INFO.get(cat, {'icon': '[*]', 'description': ''})
                conf = predictions[cat]['confidence']
                output_lines.append(f"- **{info['icon']} {cat}**: {conf:.3f}")
                if info['description']:
                    output_lines.append(f"  _{info['description']}_")
            output_lines.append("")
        else:
            output_lines.append("#### No harmful categories detected")
            output_lines.append("")
        
        # All scores in a table-like format
        output_lines.append("#### All Scores:")
        output_lines.append("| Category | Status | Confidence |")
        output_lines.append("|----------|--------|------------|")
        
        for name, data in predictions.items():
            info = LABEL_INFO.get(name, {'icon': ''})
            icon = info['icon']
            status = "YES" if data['detected'] else "NO"
            conf = data['confidence']
            bar = "#" * int(conf * 20) + "-" * (20 - int(conf * 20))
            output_lines.append(f"| {icon} {name} | {status} | {bar} {conf:.3f} |")
        
        # Summary
        summary = "CLEAN" if not result['is_harmful'] else "HARMFUL"
        
        return "\n".join(output_lines), summary
        
    except Exception as e:
        return f"ERROR: {str(e)}", ""


def predict_batch(texts: str, threshold: float, server_url: str) -> Tuple[str, str]:
    """Predict multiple texts (one per line)."""
    text_list = [t.strip() for t in texts.split('\n') if t.strip()]
    
    if not text_list:
        return "Please enter some texts", ""
    
    if len(text_list) > 100:
        return "Too many texts (max 100)", ""
    
    try:
        start = time.time()
        response = requests.post(
            f"{server_url}/predict_batch",
            json={"texts": text_list, "threshold": threshold},
            timeout=60
        )
        elapsed = (time.time() - start) * 1000
        
        if response.status_code != 200:
            return f"ERROR: {response.text}", ""
        
        result = response.json()
        results = result['results']
        
        # Format output
        output_lines = []
        output_lines.append(f"### Batch Results ({len(text_list)} texts, {elapsed:.1f}ms)")
        output_lines.append(f"Throughput: {len(text_list) / (elapsed/1000):.1f} texts/sec")
        output_lines.append("")
        
        harmful_count = sum(1 for r in results if r['is_harmful'])
        output_lines.append(f"**Summary**: {harmful_count}/{len(text_list)} texts flagged as harmful")
        output_lines.append("")
        
        for i, (text, res) in enumerate(zip(text_list, results)):
            # Truncate long texts
            display_text = text[:80] + "..." if len(text) > 80 else text
            
            if res['is_harmful']:
                output_lines.append(f"#### [{i+1}] {display_text}")
                cats = ", ".join(res['detected_categories'])
                output_lines.append(f"**Detected**: {cats}")
            else:
                output_lines.append(f"#### [{i+1}] {display_text}")
            
            # Show top 3 highest confidence scores
            preds = res['predictions']
            top3 = sorted(preds.items(), key=lambda x: x[1]['confidence'], reverse=True)[:3]
            scores = [f"{name}: {data['confidence']:.3f}" for name, data in top3]
            output_lines.append(f"_Top scores: {', '.join(scores)}_")
            output_lines.append("")
        
        summary = f"Processed {len(text_list)} texts, {harmful_count} harmful"
        
        return "\n".join(output_lines), summary
        
    except Exception as e:
        return f"ERROR: {str(e)}", ""


def create_ui():
    """Create the Gradio UI."""
    
    with gr.Blocks(title="Multi-Task Toxicity & Spam Detection") as demo:
        
        gr.Markdown("""
        # Multi-Task Toxicity & Spam Detection
        
        **TCN + Performer (FAVOR+) Hybrid Model v4**
        
        *11 labels: dangerous content, hate speech, harassment, sexually explicit, toxicity, severe toxicity, threat, insult, identity attack, phish, spam*
        """)
        
        with gr.Tab("Single Prediction"):
            with gr.Row():
                with gr.Column(scale=2):
                    server_url_single = gr.Textbox(
                        value=DEFAULT_SERVER_URL,
                        label="Server URL",
                        placeholder="http://localhost:9000"
                    )
                    text_input = gr.Textbox(
                        label="Enter text to analyze",
                        placeholder="Type something here...",
                        lines=4
                    )
                    threshold_single = gr.Slider(
                        minimum=0.1,
                        maximum=0.9,
                        value=0.5,
                        step=0.05,
                        label="Detection Threshold"
                    )
                    
                    with gr.Row():
                        check_btn = gr.Button("Check Server", variant="secondary")
                        predict_btn = gr.Button("Predict", variant="primary")
                    
                    health_output = gr.Textbox(
                        label="Server Status",
                        value="Click 'Check Server' to verify connection",
                        interactive=False
                    )
                
                with gr.Column(scale=3):
                    summary_output = gr.Textbox(
                        label="Summary",
                        interactive=False,
                        visible=True
                    )
                    result_output = gr.Markdown(
                        label="Results"
                    )
            
            # Examples
            gr.Examples(
                examples=[
                    ["Thanks for the helpful information!", 0.5],
                    ["You are an idiot and your posts are garbage!", 0.5],
                    ["f u c k you stupid idiot", 0.5],
                    ["y0u 4r3 4n 1d10t", 0.5],
                    ["f i r e y o u", 0.5],
                    ["CLICK HERE NOW!!! www.scam-site.com FREE MONEY!!!", 0.5],
                    ["All people from that country are criminals!", 0.5],
                    ["Your account has been suspended. Click here to verify.", 0.5],
                ],
                inputs=[text_input, threshold_single],
                label="Example Inputs"
            )
            
            check_btn.click(
                fn=check_health,
                inputs=[server_url_single],
                outputs=[health_output]
            )
            
            predict_btn.click(
                fn=predict_single,
                inputs=[text_input, threshold_single, server_url_single],
                outputs=[result_output, summary_output]
            )
        
        with gr.Tab("Batch Prediction"):
            with gr.Row():
                with gr.Column(scale=2):
                    server_url_batch = gr.Textbox(
                        value=DEFAULT_SERVER_URL,
                        label="Server URL",
                        placeholder="http://localhost:9000"
                    )
                    batch_input = gr.Textbox(
                        label="Enter texts (one per line)",
                        placeholder="Text 1\nText 2\nText 3...",
                        lines=10
                    )
                    threshold_batch = gr.Slider(
                        minimum=0.1,
                        maximum=0.9,
                        value=0.5,
                        step=0.05,
                        label="Detection Threshold"
                    )
                    batch_predict_btn = gr.Button("Predict Batch", variant="primary")
                
                with gr.Column(scale=3):
                    batch_summary = gr.Textbox(
                        label="Summary",
                        interactive=False
                    )
                    batch_output = gr.Markdown(
                        label="Results"
                    )
            
            batch_predict_btn.click(
                fn=predict_batch,
                inputs=[batch_input, threshold_batch, server_url_batch],
                outputs=[batch_output, batch_summary]
            )
        
        with gr.Tab("About"):
            gr.Markdown("""
            ## About This Model
            
            This is a **Multi-Task Classifier** for content moderation with **11 output labels**:
            
            ### Toxicity Categories (9 labels)
            | Label | Description |
            |-------|-------------|
            | dangerous_content | Content promoting dangerous/illegal activities |
            | hate_speech | Attacks on protected groups |
            | harassment | Targeting individuals with abuse |
            | sexually_explicit | Sexual content or solicitation |
            | toxicity | General toxic behavior |
            | severe_toxicity | Extremely toxic content |
            | threat | Threats of violence |
            | insult | Personal attacks |
            | identity_attack | Attacks based on identity |
            
            ### Spam Categories (2 labels)
            | Label | Description |
            |-------|-------------|
            | phish | Phishing attempts |
            | spam | Unwanted promotional content |
            
            ### Architecture
            - **TCN (Temporal Convolutional Network)**: Captures local patterns
            - **Performer (FAVOR+)**: Linear attention for long-range dependencies - O(L) complexity
            - **Total Parameters**: ~10M
            
            ### Features
            - Resistant to common bypass techniques:
              - Character spacing (e.g., "f u c k")
              - Leetspeak (e.g., "f|_|ck")
              - Emoji injection
              - Zero-width characters
            
            ### API Endpoints
            - `GET /` - Health check
            - `POST /predict` - Single prediction (with dynamic batching)
            - `POST /predict_batch` - Direct batch prediction
            - `GET /stats` - Server statistics
            """)
    
    return demo


def main():
    """Run the Gradio UI."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Multi-Task Inference Gradio UI")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=7860, help="Port to bind to")
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL, help="Default inference server URL")
    parser.add_argument("--share", action="store_true", help="Create public share link")
    
    args = parser.parse_args()
    
    print("="*60)
    print("MULTI-TASK INFERENCE GRADIO UI")
    print("="*60)
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Default Server: {args.server_url}")
    print(f"Share: {args.share}")
    print("="*60)
    
    demo = create_ui()
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        show_error=True
    )


if __name__ == "__main__":
    main()
