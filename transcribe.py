import os
import time
from pathlib import Path
from dotenv import load_dotenv
from moviepy import VideoFileClip
from pydub import AudioSegment
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




def slice_audio_into_chunks(audio_path: Path, temp_dir: Path, chunk_length_min: int = 8, overlap_sec: int = 15) -> list[Path]:
    """Slices a master MP3 into smaller overlapping chunks so Gemini doesn't drop dialogue."""
    print(f"🔪 Slicing {audio_path.name} into {chunk_length_min}-minute chunks (with a {overlap_sec}s overlap)...")
    
    audio = AudioSegment.from_mp3(str(audio_path))
    duration_ms = len(audio)
    
    chunk_length_ms = chunk_length_min * 60 * 1000
    overlap_ms = overlap_sec * 1000
    
    chunk_paths = []
    start = 0
    chunk_idx = 1
    
    video_temp_dir = temp_dir / audio_path.stem
    video_temp_dir.mkdir(parents=True, exist_ok=True)
    
    while start < duration_ms:
        end = start + chunk_length_ms
        
        # NEU: Wenn der nächste Schritt weniger als 1 Minute übrig lassen würde,
        # dehnen wir diesen Chunk einfach bis ganz zum Ende aus und brechen ab!
        if duration_ms - end < 60 * 1000:
            end = duration_ms
            
        chunk = audio[start:end]
        
        chunk_file_path = video_temp_dir / f"{audio_path.stem}_part_{chunk_idx:02d}.mp3"
        chunk.export(str(chunk_file_path), format="mp3", bitrate="64k")
        chunk_paths.append(chunk_file_path)
        
        print(f"   💾 Created chunk {chunk_idx:02d}: {chunk_file_path.name} (Time: {start//1000}s to {min(end, duration_ms)//1000}s)")
        
        if end == duration_ms:
            break
            
        start += chunk_length_ms - overlap_ms
        chunk_idx += 1
        
    return chunk_paths



def transcribe_chunk_with_backoff(chunk_path: Path, start_offset_sec: int) -> str:
    """Uploads and transcribes audio, protecting against free-tier rate limits via backoff."""
    retries = 5
    delay = 10  # Start with a 10-second delay if limited


    # Convert the seconds offset into a readable string (e.g., 465 seconds -> "07:45")
    minutes = start_offset_sec // 60
    seconds = start_offset_sec % 60
    timestamp_offset_str = f"{minutes:02d}:{seconds:02d}"

    for attempt in range(retries):
        uploaded_file = None
        try:
            print(f"📤 Uploading {chunk_path.name} to Gemini File API...")
            uploaded_file = client.files.upload(file=chunk_path)

            # Wait for Google file metadata processing to clear (25 min files need extra time!)
            while uploaded_file.state.name == "PROCESSING":
                print("⏳ Waiting for file metadata processing (polling every 10s)...")
                time.sleep(10)
                uploaded_file = client.files.get(name=uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                raise ValueError("File processing failed on Google servers.")

            print(f"   🤖 Transcribing chunk with gemini-3.5-flash (Offset: {timestamp_offset_str})...")
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[
                    f"This audio is a chunk from an episode of the 1974 classic anime series 'Heidi' (German dub).\n"
                    f"Generate a highly accurate, word-for-word transcript in German with TIMESTAMPS.\n\n"
                    f"STRICT FORMATTING & TRANSCRIPTION RULES:\n"
                    f"1. **Absolute Timestamps (Crucial)**: This audio chunk starts at exactly {timestamp_offset_str} in the master video.\n"
                    f"   You must calculate all timestamps relative to this start offset. Add {timestamp_offset_str} to the elapsed time of any dialogue you hear in this file.\n"
                    f"   - Format: **Speaker** ([MM:SS]): Dialogue\n"
                    f"   - Example: If a line occurs 1 minute and 10 seconds into this chunk, and your offset is {timestamp_offset_str}, add them together and stamp it accordingly.\n"
                    f"2. **Canonical Spelling**: Use your canonical world knowledge of the 'Heidi' series to ensure correct spelling of names and places:\n"
                    f"   - Characters: Heidi, Alm-Öhi, Peter, Clara, Tante Dete, Fräulein Rottenmeier, Brigitte, Sebastian, Herr Sesemann, Großmutter Sesemann, Bärbel.\n"
                    f"   - Places: Dörfli, Maienfeld, Frankfurt, die Alm.\n"
                    f"3. **Script Style**: Format the output cleanly like a theatrical script. Bold the speaker names.\n"
                    f"4. **No Meta-Text**: Do NOT include background noises, music cues (e.g., [Musik]), stage directions, or intro/outro text. Output only the clean dialogue lines.\n"
                    f"5. **Grammar**: Maintain perfect German grammar, capitalization, punctuation, and logical paragraph breaks.",
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
            if e.code in (429, 503):
                status_msg = "Rate limit hit" if e.code == 429 else "Server temporarily unavailable (503)"
                print(f"   ⚠️ {status_msg}. Backing off for {delay} seconds (Attempt {attempt+1}/{retries})...")
                time.sleep(delay)
                delay *= 2
                continue
            else:
                print(f"   ❌ API Error: {e}")
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
    temp_dir = Path("./temp_chunks")
    transcript_dir = Path("./transcripts")

    # Ensure all directories exist locally
    for folder in [video_dir, audio_dir, temp_dir, transcript_dir]:
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

        # Step 2: Slice the master audio into 8-minute chunks
        chunks = slice_audio_into_chunks(audio_path, temp_dir)
        
        # Step 3: Transcribe each chunk sequentially
        stitched_transcript = []
        pipeline_failed = False
        
        # Define settings used during slicing so our offset math aligns perfectly
        chunk_length_min = 8
        overlap_sec = 15


        for c_idx, chunk_path in enumerate(chunks, start=1):
            # Calculate how many seconds into the video this chunk starts:
            # Chunk 1 (c_idx=1) -> 0 seconds
            # Chunk 2 (c_idx=2) -> (8 * 60) - 15 = 465 seconds (07:45)
            if c_idx == 1:
                start_offset_sec = 0
            else:
                start_offset_sec = (c_idx - 1) * (chunk_length_min * 60 - overlap_sec)

            print(f" -> [{c_idx}/{len(chunks)}] Processing chunk: {chunk_path.name}")
            # PASS THE START OFFSET TO THE FUNCTION
            chunk_text = transcribe_chunk_with_backoff(chunk_path, start_offset_sec)
                
            stitched_transcript.append(chunk_text.strip())
            
            # Cooldown to protect rate limits between chunks
            time.sleep(10)

        if pipeline_failed:
            continue

        # Step 4: Stitch and save the complete file
        full_text = "\n\n=== CHUNK TRANSCRIPTION ===\n\n".join(stitched_transcript)
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        print(f"🎉 Saved complete stitched transcript: {transcript_path.name}")
        
        # Step 5: Clean up local temporary chunks to save disk space
        print("🧹 Cleaning up local temporary chunks...")
        for chunk_path in chunks:
            try:
                chunk_path.unlink()
            except:
                pass
        try:
            (temp_dir / video_path.stem).rmdir()
        except:
            pass


if __name__ == "__main__":
    main()