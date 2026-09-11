"""Proceso aislado para Windows.Media.Ocr; protocolo JSON local sin red."""

import asyncio
import json
import sys


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


async def run(language_tag):
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile

        engine = OcrEngine.try_create_from_language(Language(language_tag))
        if engine is None:
            raise ValueError(f"No está instalado el reconocimiento OCR local para {language_tag}.")
        emit(
            {
                "ready": True,
                "engine": "windows.media.ocr",
                "language": engine.recognizer_language.language_tag,
                "max_dimension": OcrEngine.max_image_dimension,
                "available_languages": [
                    x.language_tag for x in OcrEngine.available_recognizer_languages
                ],
            }
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        emit({"ready": False, "error": f"No se pudo iniciar el OCR local: {exc}"})
        return
    for line in sys.stdin:
        stream = bitmap = None
        response = None
        try:
            request = json.loads(line)
            file = await StorageFile.get_file_from_path_async(request["path"])
            stream = await file.open_async(FileAccessMode.READ)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            if max(bitmap.pixel_width, bitmap.pixel_height) > OcrEngine.max_image_dimension:
                raise ValueError("La imagen supera las dimensiones admitidas por OCR local.")
            result = await asyncio.wait_for(engine.recognize_async(bitmap), timeout=30)
            response = {"ok": True, "text": "\n".join(line.text for line in result.lines)}
        except Exception as exc:
            # The parent treats this as a pending page, never as an empty successful read.
            response = {"ok": False, "error": f"OCR local: {exc}"}
        finally:
            if bitmap is not None:
                bitmap.close()
            if stream is not None:
                stream.close()
        # Release the file handle before the parent removes its temporary PNG on Windows.
        emit(response)


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else "es-ES"))
