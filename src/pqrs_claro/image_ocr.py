"""Normalización temporal de PNG/JPEG para OCR; nunca modifica el original."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .models import DomainError

IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}


def validate_image(data, suffix):
    """Check decoded format and frame count independently of the filename or plan."""
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != IMAGE_FORMATS.get(suffix.lower()):
                raise DomainError("La imagen original no corresponde a su extensión PNG/JPEG.")
            if getattr(image, "n_frames", 1) != 1:
                raise DomainError(
                    "La imagen tiene varios fotogramas; requiere extracción específica."
                )
            size = image.size
            image.verify()
            return size
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DomainError("No se pudo decodificar la imagen original.") from exc


def normalized_image_png(data, suffix, *, max_dimension=3200):
    """Honor EXIF orientation and bound a temporary raster, including opaque alpha."""
    validate_image(data, suffix)
    if type(max_dimension) is not int or max_dimension < 1:
        raise DomainError("El límite de dimensiones OCR no es válido.")
    with Image.open(BytesIO(data)) as image:
        orientation = image.getexif().get(274, 1)
        with ImageOps.exif_transpose(image) as oriented:
            rgba = oriented.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, "white")
            canvas.alpha_composite(rgba)
            rgb = canvas.convert("RGB")
            scale = min(2.0, max_dimension / max(rgb.size))
            size = tuple(max(1, min(max_dimension, round(value * scale))) for value in rgb.size)
            raster = rgb.resize(size, Image.Resampling.LANCZOS)
            output = BytesIO()
            raster.save(output, format="PNG")
            metadata = {
                "original_size": list(image.size),
                "raster_size": list(raster.size),
                "exif_orientation": orientation,
            }
            raster.close()
            rgb.close()
            canvas.close()
            rgba.close()
            return output.getvalue(), metadata
