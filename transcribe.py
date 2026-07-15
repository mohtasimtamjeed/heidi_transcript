import os
from pathlib import Path
# from moviepy.editor import VideoFileClip
from moviepy import VideoFileClip


def extract_audio_if_needed(video_path: Path, audio_dir: Path) -> Path:
    """Extracts a lightweight, mono audio channel from a video file to keep uploads fast."""
    output_mp3_path = audio_dir / f"{video_path.stem}.mp3"
    
    # RESUME CHECK: If we already extracted this audio, don't waste time doing it again
    if output_mp3_path.exists():
        print(f"⏭️ Audio already exists for: {video_path.name}")
        return output_mp3_path
        
    print(f"🎬 Extracting audio from: {video_path.name}...")
    try:
        video = VideoFileClip(str(video_path))
        # Compress audio heavily: 64kbps, mono channels, and 16kHz sampling (perfect for speech)
        video.audio.write_audiofile(
            str(output_mp3_path), 
            bitrate="64k",
            nbytes=2,
            fps=16000,
            logger=None  # Suppress moviepy's verbose command line progress bars
        )
        video.close()
        print(f"✅ Created: {output_mp3_path.name}")
        return output_mp3_path
    except Exception as e:
        print(f"❌ Extraction failed for {video_path.name}: {e}")
        return None

def main():
    # Define local project directories
    video_dir = Path("./input_videos")
    audio_dir = Path("./output_audios")
    transcript_dir = Path("./transcripts")

    # Ensure all directories exist locally
    for folder in [video_dir, audio_dir, transcript_dir]:
        folder.mkdir(exist_ok=True)

    # Gather matching video files (.mp4, .mpg, .mpeg)
    video_extensions = ('.mp4', '.mpg', '.mpeg')
    video_files = sorted([f for f in video_dir.iterdir() if f.suffix.lower() in video_extensions])
    
    if not video_files:
        print(f"No video files found in '{video_dir.resolve()}'.")
        print("💡 Action: Drop a small .mp4 or .mpg file inside 'input_videos' to test!")
        return

    print(f"Found {len(video_files)} video files. Starting extraction pipeline...\n" + "="*40)

    for idx, video_path in enumerate(video_files, start=1):
        print(f"\n[{idx}/{len(video_files)}] Processing: {video_path.name}")
        audio_path = extract_audio_if_needed(video_path, audio_dir)


if __name__ == "__main__":
    main()