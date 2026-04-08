# Audio & Images Guide

How the claude-bot handles images, voice messages, audio files, and document attachments received via Telegram.

## Image Handling

### Photo Messages

When a user sends a photo in Telegram, the bot receives an array of image sizes. It always selects the **last entry** (highest resolution) and downloads it via the Telegram Bot API.

**Flow:**

1. Telegram sends the message with a `photo` array (multiple resolutions).
2. The bot picks the highest-resolution variant (`photos[-1]`).
3. `_download_telegram_file()` calls `getFile` on the Telegram API to get a `file_path`.
4. The file is downloaded from `https://api.telegram.org/file/bot{token}/{file_path}`.
5. The image is saved to `/tmp/claude-bot-images/` with a timestamped filename.
6. A prompt is built: `[Imagem recebida e salva em: /tmp/claude-bot-images/{filename}]` plus the user's caption (defaulting to "Analise esta imagem.").
7. The prompt is forwarded to Claude Code CLI via `_handle_text()`. Claude Code can natively read images from the filesystem.

### Documents Sent as Images

When a user sends an image as a document (file attachment), the bot checks `mime_type`. If it starts with `image/`, the same download-and-prompt flow is used. Non-image documents are currently not processed.

### Temp File Directory

All downloaded images land in:

```
/tmp/claude-bot-images/
```

This directory is created on bot startup. Files are **not automatically cleaned up** -- they persist until the OS clears `/tmp` on reboot or manual cleanup. The filename format is `{unix_timestamp}_{original_stem}{ext}`.

### Download Mechanism

The `_download_telegram_file()` method handles all Telegram file downloads:

```python
def _download_telegram_file(self, file_id: str, save_dir: Path = TEMP_IMAGES_DIR) -> Optional[Path]:
```

- Uses `urllib.request.urlopen()` with a **30-second timeout**.
- Returns the local `Path` on success, or `None` on failure.
- Logs both successful downloads and errors.

If the download fails, the bot sends an error message to the user.

## Audio / Voice Messages

### Prerequisites

Voice transcription requires two external tools:

| Tool | Purpose | Install |
|------|---------|---------|
| **ffmpeg** | Convert Telegram's OGG/Opus audio to WAV (16kHz mono) | `brew install ffmpeg` |
| **hear** | Transcribe WAV to text using Apple's SFSpeechRecognizer | Auto-installed via `./claude-bot.sh install-deps` |

The bot checks for both tools at startup via `_check_voice_tools()`:

1. **ffmpeg**: Checks `FFMPEG_PATH` (default `/opt/homebrew/bin/ffmpeg`), then falls back to `shutil.which("ffmpeg")`.
2. **hear**: Checks `HEAR_PATH` env var, then `~/.claude-bot/bin/hear` (bundled location), then system `PATH`.

If either tool is missing, voice messages trigger a warning instead of transcription.

### Transcription Flow

```
Telegram voice/audio msg
   |
   v
Download OGG file to /tmp/claude-bot-audio/
   |
   v
ffmpeg: convert OGG -> WAV (16kHz, mono)
   |
   v
hear: transcribe WAV -> text (using Apple SFSpeechRecognizer)
   |
   v
Send transcribed text to Claude Code CLI as a regular text prompt
```

**Detailed steps:**

1. The bot detects a `voice` or `audio` field in the incoming message.
2. A status message is sent: "Audio recebido ({duration}s). Transcrevendo..."
3. The audio file is downloaded to `/tmp/claude-bot-audio/`.
4. `_convert_ogg_to_wav()` runs ffmpeg: `ffmpeg -y -i input.ogg -ar 16000 -ac 1 -f wav output.wav` with a 30-second timeout.
5. `_transcribe_audio()` runs hear: `hear -l {locale} -i output.wav` with a 120-second timeout.
6. If transcription succeeds, a preview (first 500 chars) is shown to the user.
7. The transcription is wrapped with `[Mensagem de voz transcrita]` and sent to Claude Code CLI.

### Language Configuration

The `HEAR_LOCALE` environment variable controls the transcription language. It defaults to `pt-BR` (Brazilian Portuguese). Set it in your `.env` file:

```env
HEAR_LOCALE=en-US
```

Common values: `pt-BR`, `en-US`, `es-ES`, `fr-FR`, `de-DE`.

This maps directly to the `-l` flag of the `hear` CLI, which uses Apple's speech recognition locales.

### Audio Cleanup

Unlike images, audio temp files are cleaned up immediately after processing. Both the original OGG file and the converted WAV file are deleted in a `finally` block after the transcription completes (or fails).

## Attachments

### Supported Types

| Attachment Type | Handled | Behavior |
|----------------|---------|----------|
| Photos (compressed) | Yes | Downloaded and analyzed by Claude |
| Image documents (image/* MIME) | Yes | Same as photos |
| Voice messages | Yes | Transcribed to text (requires ffmpeg + hear) |
| Audio files (forwarded) | Yes | Same as voice messages |
| Other documents | No | Silently ignored |

### Reply Context

When a voice or image message is a reply to a previous message, the bot extracts the reply context via `_extract_reply_context()` and prepends it to the prompt sent to Claude. This maintains conversational continuity.

## Limitations

- **Telegram file size limit**: Telegram's Bot API has a 20 MB download limit for files. Larger files will fail to download.
- **Network timeout**: File downloads have a 30-second timeout. Large images on slow connections may fail.
- **ffmpeg timeout**: Audio conversion has a 30-second timeout.
- **hear timeout**: Transcription has a 120-second timeout. Very long audio messages may fail.
- **Image persistence**: Downloaded images in `/tmp/claude-bot-images/` are not auto-cleaned. They accumulate until OS reboot or manual cleanup.
- **No non-image documents**: PDFs, text files, spreadsheets, etc. sent as documents are not processed.
- **Dictation requirement**: The `hear` tool requires macOS Dictation to be enabled (System Settings > Keyboard > Dictation).
- **macOS only**: The `hear` tool uses Apple's SFSpeechRecognizer, so voice transcription only works on macOS.
