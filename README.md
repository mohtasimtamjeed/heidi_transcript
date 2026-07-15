# 🏔️ Heidi Anime Transcriber

## 🎯 The Problem: Heidi Has No German Subtitles

I was watching *Heidi* (the classic 1974 anime) *auf Deutsch* (in German) to practice my German (but mostly because I remember watching it as a child fondly). While it is highly beneficial to let the native sounds, rhythms, and intonations wash over you, [there are no official German subtitles available for this dub.](https://www.reddit.com/r/German/comments/1c8o59w/heidi_in_german/) I felt that a reinforcement of textual input would significantly improve my understanding and enjoyment.

---

## 💡 The Solution: Resilient Multi-Chunk Audio Transcription Pipeline

To bridge this gap, I designed a fault-tolerant, asynchronous-ready Python processing pipeline that automates large-scale media file transcription using the Google Gemini API. This system orchestrates end-to-end media preprocessing, dynamic audio chunking with boundary protection, and absolute timeline synchronization.

### 🏗️ System Architecture & Data Flow

```text
[ Input Video ] 
      │
      ▼
[ FFmpeg Processing ] ──► Extracts High-Fidelity Mono MP3
      │
      ▼
[ Dynamic Slicer (pydub) ] ──► Calculates 8-min chunks with 15s overlaps
      │
      ▼
[ Resilient API Client ] ──► Handles uploads + manages 429/503 exponential backoff
      │
      ▼
[ Prompt Engineering Engine ] ──► Injects absolute time-offset & canonical "Heidi" constraints
      │
      ▼
[ Final Stitched Script ] ──► Continuous, absolute-timestamped German transcript
```

---

## 🛠️ Key Engineering Challenges & Solutions

### 1. Dynamic Timestamp Offsetting (Relative to Absolute Time Mapping)
> **The Problem:** LLM APIs analyze individual audio chunks in isolation. A 10-second clip inside "Chunk 2" would naturally be transcribed starting at `00:10` instead of its absolute position in the master video, breaking the chronological continuity of the final stitched file.
>
> **The Solution:** Implemented a mathematical start-offset calculation in the execution loop. This offset is formatted as a `MM:SS` string and dynamically injected directly into the system prompt for each respective chunk, forcing the LLM to calculate absolute global timestamps.

### 2. Micro-Chunk Mitigation Logic
> **The Problem:** Naive sliding-window slicing loops often leave a trailing "micro-chunk" at the very end of a file (e.g., a final chunk of only 6 seconds). The lack of sufficient contextual audio data frequently caused the model to hallucinate or repeat historical context out of confusion.
>
> **The Solution:** Programmed custom mathematical boundary checks within the `pydub` slicing iteration. If the remaining audio frame is calculated to be under 60 seconds, the slicing loop halts early and automatically appends the remainder to the preceding chunk. This guarantees a substantial, context-rich audio buffer for every single API call.

### 3. Network Resilience & Fault Tolerance
> **The Problem:** Orchestrating high-volume media ingestion pipelines inevitably leads to temporary network failures, rate limits (`HTTP 429`), and upstream server overloads (`HTTP 503`).
>
> **The Solution:** Engineered a robust exception-handling wrapper around the Gemini client. The network layer intercepts specific exception status codes and triggers a deterministic exponential backoff cool-down cycle (sequentially doubling the sleep delay) across a 5-attempt retry budget before gracefully raising a fatal pipe error.

---

## 🚀 Getting Started

### Prerequisites
* **Python 3.10+**
* **FFmpeg**: Must be installed and configured on your system environment variable path (enables `pydub` to interface with raw audio streams).

---

### Installation & Setup

#### 1. Clone the Repository
Clone this repository to your local machine and step into the project directory:
```bash
git clone [https://github.com/yourusername/heidi-transcript.git](https://github.com/yourusername/heidi-transcript.git)
cd heidi-transcript
```

#### 2. Configure the Virtual Environment
Create and activate an isolated Python virtual environment to keep your environment clean:

* **Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\activate
  ```
* **macOS/Linux:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

#### 3. Install Dependencies
Install all required package distributions (including `pydub`, `google-genai`, and `python-dotenv`):
```bash
pip install -r requirements.txt
```

#### 4. Configure Environment Variables
Create a file named `.env` in the root of your project directory to securely store your credentials:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

> ⚠️ **Security Note:** Never commit your `.env` file to public repositories. Ensure that `.env` is safely tracked in your `.gitignore`.

---

## 🏃‍♂️ Running the Pipeline

1. Create a folder named `input_videos` in the root directory and place your target media files (e.g., `Heidi 52.mp4`) inside it.
2. Execute the master script:
   ```bash
   python transcribe.py
   ```

### Automated Stages Executed Under the Hood:
* **Extraction:** The pipeline strips the high-fidelity audio stream from your video file.
* **Slicing:** `pydub` partitions the master audio file into optimized 8-minute segments utilizing a strict 15-second overlap window.
* **Ingestion:** Segments are uploaded to the Gemini File API, transcribed, and mathematically re-aligned for time continuity.
* **Compilation:** The script seamlessly stitches the chunk outputs together and writes a clean, globally-timestamped Markdown transcript into the `transcripts/` folder.