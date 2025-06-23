#!/usr/bin/env python3
"""
Real-time Gradio interface for testing Orpheus-FastAPI streaming TTS
This version implements truly real-time streaming audio playback.
"""

import gradio as gr
import requests
import json
import time
import tempfile
import os
import threading
import queue
from typing import Tuple, Optional
import base64
import io
import wave
import numpy as np

# Configuration
DEFAULT_BASE_URL = "https://zb7jbp4ph16jlc-5005.proxy.runpod.net"
DEFAULT_VOICES = ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"]
DEFAULT_TEXT = "Hello! This is a test of the Orpheus streaming text-to-speech system. The streaming mode should provide much lower latency compared to the regular batch processing mode."

class RealTimeStreamingTester:
    def __init__(self):
        self.base_url = DEFAULT_BASE_URL
        self.streaming_active = False
        self.audio_chunks = []
        self.chunk_timings = []
        
    def test_regular_tts(self, text: str, voice: str, base_url: str) -> Tuple[Optional[str], str]:
        """Test regular TTS endpoint"""
        if not text.strip():
            return None, "❌ Please enter some text"
        
        self.base_url = base_url.rstrip('/')
        url = f"{self.base_url}/v1/audio/speech"
        
        payload = {
            "input": text,
            "voice": voice,
            "model": "orpheus"
        }
        
        start_time = time.time()
        status_msg = f"🔄 Generating speech with voice '{voice}'...\\n"
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            
            end_time = time.time()
            total_time = end_time - start_time
            
            if response.status_code != 200:
                error_msg = f"❌ HTTP {response.status_code}: {response.text}"
                return None, status_msg + error_msg
            
            # Save audio to temporary file
            temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_file.write(response.content)
            temp_file.close()
            
            status_msg += f"✅ Regular TTS completed!\\n"
            status_msg += f"⏱️ Total time: {total_time:.3f}s\\n"
            status_msg += f"📁 Audio size: {len(response.content):,} bytes\\n"
            
            return temp_file.name, status_msg
            
        except requests.exceptions.Timeout:
            return None, status_msg + "❌ Request timed out (>120s)"
        except requests.exceptions.RequestException as e:
            return None, status_msg + f"❌ Network error: {e}"
        except Exception as e:
            return None, status_msg + f"❌ Unexpected error: {e}"
    
    def stream_tts_realtime(self, text: str, voice: str, base_url: str, buffer_size: int, padding_ms: int):
        """Stream TTS with real-time chunked audio playback"""
        if not text.strip():
            yield None, "❌ Please enter some text", "No audio generated"
            return
        
        self.base_url = base_url.rstrip('/')
        url = f"{self.base_url}/v1/audio/speech/stream"
        
        payload = {
            "input": text,
            "voice": voice,
            "buffer_size": buffer_size,
            "chunk_padding_ms": padding_ms
        }
        
        start_time = time.time()
        status_msg = f"🔄 Starting real-time streaming TTS...\\n"
        status_msg += f"⚙️ Voice: {voice}, Buffer: {buffer_size}, Padding: {padding_ms}ms\\n"
        
        # Reset streaming state
        self.streaming_active = True
        self.audio_chunks = []
        self.chunk_timings = []
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                stream=True,
                timeout=120
            )
            
            if response.status_code != 200:
                error_msg = f"❌ HTTP {response.status_code}: {response.text}"
                yield None, status_msg + error_msg, "Error occurred"
                return
            
            # Process stream in real-time chunks
            chunk_count = 0
            total_bytes = 0
            first_chunk_time = None
            accumulated_audio = b""
            header_processed = False
            wav_header = b""
            
            for chunk in response.iter_content(chunk_size=4096):
                if not self.streaming_active:
                    break
                    
                if chunk:
                    current_time = time.time()
                    
                    if first_chunk_time is None:
                        first_chunk_time = current_time
                        first_chunk_latency = first_chunk_time - start_time
                        status_msg += f"⚡ First chunk in: {first_chunk_latency:.3f}s\\n"
                    
                    accumulated_audio += chunk
                    total_bytes += len(chunk)
                    chunk_count += 1
                    
                    # Extract WAV header from first chunk
                    if not header_processed and len(accumulated_audio) >= 44:
                        wav_header = accumulated_audio[:44]
                        header_processed = True
                    
                    # Create incremental audio file for real-time playback
                    if header_processed and len(accumulated_audio) > 44:
                        # Create a proper WAV file with accumulated data
                        temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                        
                        # Write WAV header
                        temp_file.write(wav_header)
                        
                        # Write audio data
                        audio_data = accumulated_audio[44:]
                        temp_file.write(audio_data)
                        
                        # Update WAV header with correct sizes
                        temp_file.seek(4)
                        temp_file.write((len(audio_data) + 36).to_bytes(4, 'little'))
                        temp_file.seek(40)
                        temp_file.write(len(audio_data).to_bytes(4, 'little'))
                        
                        temp_file.close()
                        
                        # Update status
                        elapsed = current_time - start_time
                        status_msg_update = status_msg + f"📊 Chunk {chunk_count}: {len(chunk)} bytes at {elapsed:.2f}s\\n"
                        
                        # Store timing info
                        self.chunk_timings.append(elapsed)
                        
                        # Yield the current audio state for real-time playback
                        yield temp_file.name, status_msg_update, f"Streaming... {chunk_count} chunks received"
            
            # Final processing
            end_time = time.time()
            total_time = end_time - start_time
            
            final_status = status_msg + f"✅ Streaming completed!\\n"
            final_status += f"⏱️ Total time: {total_time:.3f}s\\n"
            final_status += f"📦 Total chunks: {chunk_count}\\n"
            final_status += f"📁 Total size: {total_bytes:,} bytes\\n"
            
            if first_chunk_time:
                first_chunk_latency = first_chunk_time - start_time
                final_status += f"🚀 First chunk latency: {first_chunk_latency:.3f}s\\n"
            
            # Create final audio file
            if accumulated_audio and len(accumulated_audio) > 44:
                final_temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                final_temp_file.write(wav_header)
                final_temp_file.write(accumulated_audio[44:])
                
                # Update WAV header
                final_temp_file.seek(4)
                final_temp_file.write((len(accumulated_audio) - 8).to_bytes(4, 'little'))
                final_temp_file.seek(40)
                final_temp_file.write((len(accumulated_audio) - 44).to_bytes(4, 'little'))
                
                final_temp_file.close()
                
                yield final_temp_file.name, final_status, "✅ Streaming completed!"
            else:
                yield None, final_status + "❌ No audio data received", "No audio generated"
                
        except requests.exceptions.Timeout:
            yield None, status_msg + "❌ Request timed out (>120s)", "Timeout error"
        except requests.exceptions.RequestException as e:
            yield None, status_msg + f"❌ Network error: {e}", "Network error"
        except Exception as e:
            yield None, status_msg + f"❌ Unexpected error: {e}", "Unexpected error"
        finally:
            self.streaming_active = False

    def stop_streaming(self):
        """Stop active streaming"""
        self.streaming_active = False
        return "🛑 Streaming stopped", "Stopped"

def create_interface():
    """Create the Gradio interface for real-time streaming tests"""
    tester = RealTimeStreamingTester()
    
    with gr.Blocks(title="Orpheus Real-Time Streaming TTS Tester", theme=gr.themes.Soft()) as interface:
        gr.Markdown("""
        # 🎤 Orpheus Real-Time Streaming TTS Tester
        
        This interface tests the Orpheus-FastAPI streaming TTS endpoint with **real-time audio playback**.
        The streaming mode plays audio chunks as they arrive, providing immediate feedback.
        """)
        
        with gr.Row():
            with gr.Column(scale=2):
                text_input = gr.Textbox(
                    label="Text to Synthesize",
                    placeholder="Enter text to convert to speech...",
                    value=DEFAULT_TEXT,
                    lines=3,
                    max_lines=10
                )
                
                with gr.Row():
                    voice_selector = gr.Dropdown(
                        choices=DEFAULT_VOICES,
                        label="Voice",
                        value="tara"
                    )
                    base_url_input = gr.Textbox(
                        label="API Base URL",
                        value=DEFAULT_BASE_URL,
                        placeholder="https://your-api-endpoint.com"
                    )
            
            with gr.Column(scale=1):
                gr.Markdown("### Streaming Controls")
                
                buffer_size_slider = gr.Slider(
                    minimum=5,
                    maximum=100,
                    value=40,
                    step=5,
                    label="Buffer Size (token groups)",
                    info="Higher = better quality, higher latency"
                )
                
                padding_slider = gr.Slider(
                    minimum=0,
                    maximum=50,
                    value=5,
                    step=1,
                    label="Chunk Padding (ms)",
                    info="Silence between audio chunks"
                )
        
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 🎯 Regular TTS (Batch Mode)")
                regular_btn = gr.Button("🎵 Generate Regular TTS", variant="secondary", size="lg")
                regular_audio = gr.Audio(label="Regular TTS Output", type="filepath")
                regular_status = gr.Textbox(
                    label="Regular TTS Status",
                    lines=8,
                    max_lines=15
                )
            
            with gr.Column():
                gr.Markdown("### ⚡ Streaming TTS (Real-Time Mode)")
                with gr.Row():
                    streaming_btn = gr.Button("🚀 Start Real-Time Streaming", variant="primary", size="lg")
                    stop_btn = gr.Button("🛑 Stop Streaming", variant="stop", size="sm")
                
                streaming_audio = gr.Audio(label="Streaming TTS Output (Real-Time)", type="filepath", autoplay=True)
                streaming_status = gr.Textbox(
                    label="Streaming Status",
                    lines=8,
                    max_lines=15
                )
                streaming_info = gr.Textbox(
                    label="Real-Time Info",
                    lines=2,
                    max_lines=3
                )
        
        # Event handlers
        regular_btn.click(
            fn=tester.test_regular_tts,
            inputs=[text_input, voice_selector, base_url_input],
            outputs=[regular_audio, regular_status],
            show_progress=True
        )
        
        streaming_btn.click(
            fn=tester.stream_tts_realtime,
            inputs=[text_input, voice_selector, base_url_input, buffer_size_slider, padding_slider],
            outputs=[streaming_audio, streaming_status, streaming_info],
            show_progress=False  # Don't show progress bar for streaming
        )
        
        stop_btn.click(
            fn=tester.stop_streaming,
            outputs=[streaming_status, streaming_info]
        )
        
        # Auto-refresh streaming output every 0.5 seconds when streaming
        interface.load(
            None,
            js="""
            function() {
                // Enable auto-refresh for streaming audio
                setInterval(function() {
                    const streamingAudio = document.querySelector('audio');
                    if (streamingAudio && streamingAudio.src) {
                        // Force reload of audio when source changes
                        streamingAudio.load();
                    }
                }, 500);
                return null;
            }
            """
        )
    
    return interface

if __name__ == "__main__":
    print("🚀 Starting Orpheus Real-Time Streaming TTS Tester...")
    print("This interface provides real-time streaming audio playback!")
    
    interface = create_interface()
    interface.launch(
        server_name="0.0.0.0",
        server_port=7861,
        share=False,
        show_error=True,
        debug=True
    )
