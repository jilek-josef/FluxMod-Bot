import fluxer

class EmbedBuilder:
    @staticmethod
    def build_embed(title: str, description: str, color: int) -> fluxer.Embed:
        embed = fluxer.Embed(title=title, description=description, color=color)
        return embed
    
    # Preset colors
    @staticmethod
    def success_embed(title: str, description: str) -> fluxer.Embed:
        return EmbedBuilder.build_embed(title, description, 0x28A745)
    @staticmethod
    def error_embed(title: str, description: str) -> fluxer.Embed:
        return EmbedBuilder.build_embed(title, description, 0xDC3545)
    @staticmethod
    def info_embed(title: str, description: str) -> fluxer.Embed:
        return EmbedBuilder.build_embed(title, description, 0x17A2B8)
    @staticmethod
    def warning_embed(title: str, description: str) -> fluxer.Embed:
        return EmbedBuilder.build_embed(title, description, 0xFFC107)
    

    #User-friendly method to create embeds with optional fields
    @staticmethod
    def create_embed(
        title: str,
        description: str,
        color: int = 0x5865F2,
        footer: str | None = None,
        thumbnail_url: str | None = None,
        image_url: str | None = None,
    ) -> fluxer.Embed:
        embed = EmbedBuilder.build_embed(title, description, color)
        if footer:
            embed.set_footer(text=footer)
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        if image_url:
            embed.set_image(url=image_url)
        return embed
    
    #usage examples

    """
    basic_embed = EmbedBuilder.build_embed("Hello", "This is a basic embed", 0x5865F2)
    success_embed = EmbedBuilder.success_embed("Success!", "Your action was successful.")
    error_embed = EmbedBuilder.error_embed("Error!", "Something went wrong.")
    info_embed = EmbedBuilder.info_embed("Info", "This is some information.")
    warning_embed = EmbedBuilder.warning_embed("Warning!", "This is a warning.")
    custom_embed = EmbedBuilder.create_embed(
        title="Custom Embed",
        description="This embed has a thumbnail and footer.",
        color=0xFF5733,
        footer="This is the footer",
        thumbnail_url="https://example.com/thumbnail.png",
        image_url="https://example.com/image.png"
    )
    """