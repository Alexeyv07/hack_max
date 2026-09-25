"""
Скрипт конвертирует все MP4 файлы в текущей папке в анимированные WebP.
Требует установленный ffmpeg в системе.
"""

import subprocess
import sys
from pathlib import Path


def check_ffmpeg() -> bool:
    """Проверяет наличие ffmpeg в системе."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def convert_mp4_to_webp(
    input_file: Path,
    quality: int = 80,
    fps: int = 15,
    width: int = 480,
) -> bool:
    """
    Конвертирует один MP4 файл в WebP.

    :param input_file: путь к MP4 файлу
    :param quality: качество (0-100, больше = лучше)
    :param fps: кадров в секунду
    :param width: ширина выходного файла (высота подбирается автоматически)
    :return: True при успехе, False при ошибке
    """
    output_file = input_file.with_suffix(".webp")

    # Пропускаем, если файл уже существует
    if output_file.exists():
        print(f"⏭  Пропуск (уже существует): {output_file.name}")
        return True

    # Параметры ffmpeg:
    # -vf scale=...:WIDTH:-1  — масштабирование с сохранением пропорций
    # -loop 0                 — бесконечный цикл
    # -q:v QUALITY            — качество
    # -an                     — убрать аудио
    cmd = [
        "ffmpeg",
        "-y",  # перезапись без вопросов
        "-i",
        str(input_file),
        "-vcodec",
        "libwebp",
        "-vf",
        f"scale={width}:-1,fps={fps}",
        "-lossless",
        "0",
        "-compression_level",
        "6",
        "-q:v",
        str(quality),
        "-loop",
        "0",
        "-an",
        "-preset",
        "default",
        str(output_file),
    ]

    try:
        print(f"🎬 Конвертация: {input_file.name} -> {output_file.name}")
        subprocess.run(
            cmd,
            capture_output=True,
            check=True,
        )
        size_in = input_file.stat().st_size / 1024
        size_out = output_file.stat().st_size / 1024
        print(f"✅ Готово: {output_file.name} ({size_in:.0f} КБ -> {size_out:.0f} КБ)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при конвертации {input_file.name}:")
        print(e.stderr.decode(errors="ignore"))
        return False


def main() -> int:
    if not check_ffmpeg():
        print("❌ ffmpeg не найден в системе.")
        print("Установите его:")
        print("  macOS:   brew install ffmpeg")
        print("  Ubuntu:  sudo apt install ffmpeg")
        print("  Windows: https://ffmpeg.org/download.html")
        return 1

    # Папка, где искать MP4 (можно передать аргументом)
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()

    if not folder.is_dir():
        print(f"❌ Папка не найдена: {folder}")
        return 1

    mp4_files = sorted(folder.glob("*.mp4"))
    # Также подхватим MP4 с большими буквами расширения
    mp4_files += sorted(folder.glob("*.MP4"))
    mp4_files = list({f.resolve(): f for f in mp4_files}.values())

    if not mp4_files:
        print(f"📂 В папке {folder} нет MP4 файлов.")
        return 0

    print(f"📂 Найдено {len(mp4_files)} MP4 файл(ов) в {folder}\n")

    success = 0
    for mp4 in mp4_files:
        if convert_mp4_to_webp(mp4):
            success += 1

    print(f"\n🎉 Успешно: {success}/{len(mp4_files)}")
    return 0 if success == len(mp4_files) else 2


if __name__ == "__main__":
    sys.exit(main())
