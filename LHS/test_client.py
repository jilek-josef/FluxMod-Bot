"""
Test client for the inference server.
Simple script to test the API endpoints.
"""

import requests
import time
import concurrent.futures
import sys
from typing import List

SERVER_URL = "http://localhost:9000"


def test_health():
    """Test health endpoint."""
    print("Testing health endpoint...")
    try:
        response = requests.get(f"{SERVER_URL}/", timeout=5)
        data = response.json()
        print(f"  Status: {data['status']}")
        print(f"  Device: {data['device']}")
        print(f"  Queue: {data['queue_size']}")
        print(f"  Total Requests: {data['total_requests']}")
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def test_predict(text: str, threshold: float = 0.5):
    """Test single prediction."""
    print(f"\nTesting predict: '{text[:50]}...'" if len(text) > 50 else f"\nTesting predict: '{text}'")
    
    try:
        start = time.time()
        response = requests.post(
            f"{SERVER_URL}/predict",
            json={"text": text},  # No threshold parameter - server returns raw logits
            timeout=10
        )
        elapsed = (time.time() - start) * 1000
        
        if response.status_code != 200:
            print(f"  ERROR: {response.status_code} - {response.text}")
            return None
        
        result = response.json()
        print(f"  Time: {elapsed:.2f}ms (inference: {result.get('inference_time_ms', 0):.2f}ms)")
        
        probs = result.get('probabilities', [])
        
        # Apply threshold client-side
        label_names = ['dangerous_content', 'hate_speech', 'harassment', 'sexually_explicit',
                       'toxicity', 'severe_toxicity', 'threat', 'insult', 'identity_attack',
                       'phish', 'spam']
        
        detected = []
        for name, prob in zip(label_names, probs):
            if prob >= threshold:
                detected.append(name)
        
        is_harmful = len(detected) > 0
        print(f"  Harmful: {is_harmful}")
        
        if detected:
            print(f"  Detected: {', '.join(detected)}")
        
        # Show top 3 scores
        top3 = sorted(zip(label_names, probs), key=lambda x: x[1], reverse=True)[:3]
        print("  Top 3 scores:")
        for name, prob in top3:
            status = "✓" if prob >= threshold else " "
            print(f"    [{status}] {name}: {prob:.3f}")
        
        return result
    
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def test_predict_batch(texts: List[str], threshold: float = 0.5):
    """Test batch prediction."""
    print(f"\nTesting batch predict ({len(texts)} texts)...")
    
    try:
        start = time.time()
        response = requests.post(
            f"{SERVER_URL}/predict_batch",
            json={"texts": texts},  # No threshold parameter
            timeout=30
        )
        elapsed = (time.time() - start) * 1000
        
        if response.status_code != 200:
            print(f"  ERROR: {response.status_code} - {response.text}")
            return None
        
        result = response.json()
        print(f"  Total time: {elapsed:.2f}ms")
        print(f"  Throughput: {len(texts) / (elapsed/1000):.1f} texts/sec")
        
        harmful_count = 0
        for r in result['results']:
            probs = r.get('probabilities', [])
            for prob in probs:
                if prob >= threshold:
                    harmful_count += 1
                    break
        
        print(f"  Harmful: {harmful_count}/{len(texts)}")
        
        return result
    
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def test_concurrent(num_requests: int = 50):
    """Test concurrent requests to exercise dynamic batching."""
    print(f"\nTesting concurrent requests ({num_requests})...")
    
    texts = [
        "You are an idiot!",
        "Thanks for the help!",
        "I hate you stupid moron!",
        "Have a nice day!",
        "This is spam click here now!",
    ] * (num_requests // 5)
    
    def make_request(text):
        try:
            response = requests.post(
                f"{SERVER_URL}/predict",
                json={"text": text},  # No threshold parameter
                timeout=30
            )
            return response.status_code == 200
        except Exception:
            return False
    
    start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(make_request, texts))
    
    elapsed = time.time() - start
    success_count = sum(results)
    
    print(f"  Completed: {success_count}/{num_requests} successful")
    print(f"  Total time: {elapsed:.2f}s")
    print(f"  Throughput: {num_requests / elapsed:.1f} req/sec")
    
    return success_count == num_requests


def main():
    global SERVER_URL
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Inference Server")
    parser.add_argument("--url", default=SERVER_URL, help="Server URL")
    parser.add_argument("--concurrent", type=int, default=0, help="Run concurrent test with N requests")
    parser.add_argument("--threshold", type=float, default=0.5, help="Threshold for detection (client-side)")
    
    args = parser.parse_args()
    
    SERVER_URL = args.url
    threshold = args.threshold
    
    print("="*60)
    print("INFERENCE SERVER TEST CLIENT")
    print("="*60)
    print(f"Server: {SERVER_URL}")
    print("="*60)
    
    # Test health
    if not test_health():
        print("\nServer not available. Exiting.")
        sys.exit(1)
    
    # Test single predictions
    test_cases = [
        "Thanks for the helpful information!",
        "You are an idiot and your posts are garbage!",
        "f u c k you stupid idiot",
        "y0u 4r3 4n 1d10t",
        "CLICK HERE NOW!!! www.scam-site.com FREE MONEY!!!",
        "All people from that country are criminals!",
        "Your account has been suspended. Click here to verify.",
    ]
    
    for text in test_cases:
        test_predict(text, threshold=threshold)
        time.sleep(0.1)  # Small delay between requests
    
    # Test batch
    test_predict_batch(test_cases, threshold=threshold)
    
    # Test concurrent if requested
    if args.concurrent > 0:
        test_concurrent(args.concurrent)
    
    # Final stats
    print("\n" + "="*60)
    print("Fetching server stats...")
    try:
        response = requests.get(f"{SERVER_URL}/stats", timeout=5)
        stats = response.json()
        print(f"  Total requests: {stats.get('total_requests', 0)}")
        print(f"  Total batches: {stats.get('total_batches', 0)}")
        print(f"  Total items: {stats.get('total_items_processed', 0)}")
        print(f"  Queue high water mark: {stats.get('queue_high_water_mark', 0)}")
    except Exception as e:
        print(f"  ERROR: {e}")
    
    print("="*60)
    print("Tests complete!")


if __name__ == "__main__":
    main()
