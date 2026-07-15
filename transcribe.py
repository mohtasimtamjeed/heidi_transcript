import os
import time
from pathlib import Path
from dotenv import load_dotenv
from moviepy import VideoFileClip
from google import genai
from google.genai.errors import APIError

# Load environment configs from our local .env file
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY is missing from your .env file.")

# Initialize the official GenAI Client
client = genai.Client(api_key=API_KEY)

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


def transcribe_with_backoff(audio_path: Path) -> str:
    """Uploads and transcribes audio, protecting against free-tier rate limits via backoff."""
    retries = 5
    delay = 10  # Start with a 10-second delay if limited

    for attempt in range(retries):
        uploaded_file = None
        try:
            print(f"📤 Uploading {audio_path.name} to Gemini File API...")
            uploaded_file = client.files.upload(file=audio_path)

            # Wait for Google file metadata processing to clear (25 min files need extra time!)
            while uploaded_file.state.name == "PROCESSING":
                print("⏳ Waiting for file metadata processing (polling every 10s)...")
                time.sleep(10)
                uploaded_file = client.files.get(name=uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                raise ValueError("File processing failed on Google servers.")

            print("🤖 Requesting German text transcript from gemini-3.5-flash...")
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[
                    """This audio is an episode from the 1974 classic anime series 'Heidi' (German dub). 
        
        Generate a highly accurate, word-for-word transcript in German with TIMESTAMPS.
        Please apply the following guidelines:
        1. Use its canonical world knowledge of the series to ensure correct spelling of names and places (e.g., Heidi, Tante Dete, Alm-Öhi, Peter, Barbel, Dörfli, Maienfeld).
        2. Format it like a script with clear speaker labels and timestamps.
        3. Maintain correct German punctuation and paragraph breaks.""",
            
        # 3. Insert a timestamp in the format [MM:SS] at the beginning of each speaker's turn, or whenever there is a significant pause/scene transition.
        # 4. Include brief, helpful contextual stage directions in parentheses with timestamps where appropriate (e.g., when the theme song starts/ends, or during long musical sequences).
                    uploaded_file
                ]
            )
            



            # Clean up storage footprint immediately
            print("🧹 Cleaning up remote file from Gemini servers...")
            client.files.delete(name=uploaded_file.name)
            return response.text

        except APIError as e:
            # Clean up the file if it was uploaded before the API error triggered
            if uploaded_file:
                try:
                    client.files.delete(name=uploaded_file.name)
                except:
                    pass

            # Check if error is a rate limit hit (HTTP 429)
            if e.code == 429:
                print(f"⚠️ Rate limit hit. Backing off for {delay} seconds (Attempt {attempt+1}/{retries})...")
                time.sleep(delay)
                delay *= 2  # Double the wait time for the next potential hit
                continue
            else:
                print(f"❌ API Error: {e}")
                return None
        except Exception as e:
            print(f"❌ Unexpected Error: {e}")
            return None
            
    print("❌ Max retries exhausted due to heavy rate-limiting.")
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

    print(f"Found {len(video_files)} video files. Starting pipeline...\n" + "="*40)

    for idx, video_path in enumerate(video_files, start=1):
        transcript_path = transcript_dir / f"{video_path.stem}_transcript.txt"
        
        # RESUME CHECK: Skip entirely if transcript already exists!
        if transcript_path.exists():
            print(f"[{idx}/{len(video_files)}] Skipping {video_path.name} (Transcript already exists).")
            continue

        print(f"\n[{idx}/{len(video_files)}] Processing: {video_path.name}")
        
        # Step 1: Video to MP3
        audio_path = extract_audio_if_needed(video_path, audio_dir)
        if not audio_path:
            continue

        # Step 2: Send to API with smart retry checks
        transcript_text = transcribe_with_backoff(audio_path)
        if not transcript_text:
            print(f"⏭️ Skipping {video_path.name} due to an unrecoverable failure.")
            continue

        # Step 3: Write out transcript
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript_text)
        print(f"💾 Saved transcript successfully: {transcript_path.name}")
        
        # Safe Cooldown: Keeps our Token-Per-Minute usage window clear
        print("☕ Taking a 15-second breathing room pause to protect free-tier TPM...")
        time.sleep(15)


if __name__ == "__main__":
    main()