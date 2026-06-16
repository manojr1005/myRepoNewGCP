"""
TTS Audio Generation Module
Generates 12 audio variations per utterance (2 genders × 6 accents)

PROPRIETARY NOTICE:
This code is proprietary and belongs to Miratech.
Copyright (c) Miratech. All rights reserved.
Contact: Nikhil.Kodilkar@gmail.com
"""

import os
import sys
import pandas as pd
import asyncio
import edge_tts
from pathlib import Path
import json
import requests

# Try to import Google Cloud TTS
try:
    from google.cloud import texttospeech
    GOOGLE_TTS_AVAILABLE = True
except ImportError:
    GOOGLE_TTS_AVAILABLE = False
    print("[WARNING] google-cloud-texttospeech not installed. Google TTS will not be available.")

# Try to import Azure TTS
try:
    import azure.cognitiveservices.speech as speechsdk
    AZURE_TTS_AVAILABLE = True
except ImportError:
    AZURE_TTS_AVAILABLE = False
    print("[WARNING] azure-cognitiveservices-speech not installed. Azure TTS will not be available.")

# Try to import pydub, fallback to soundfile if audioop issue
try:
    from pydub import AudioSegment
    USE_PYDUB = True
except (ImportError, ModuleNotFoundError) as e:
    if 'audioop' in str(e) or 'pyaudioop' in str(e):
        try:
            import soundfile as sf
            import numpy as np
            USE_PYDUB = False
        except ImportError:
            print("Error: Need either pydub (with audioop) or soundfile installed")
            print("Install soundfile: pip install soundfile scipy")
            sys.exit(1)
    else:
        raise

# Configuration
ACCENTS = [
    'indian_english',
    'french_english', 
    'chinese_english',
    'spanish_english',
    'australian_english',
    'regular_english'
]

GENDERS = ['male', 'female']


async def discover_voices_edge():
    """Discover available Edge TTS voices and map them to our accent/gender requirements"""
    print("="*60)
    print("🔍 Discovering available Edge TTS voices...")
    print("="*60)
    
    print("  Connecting to Edge TTS service...", end=" ", flush=True)
    try:
        voices = await edge_tts.list_voices()
        print(f"✓ Found {len(voices)} total voices")
        print(f"[DEBUG] Successfully retrieved {len(voices)} voices from Edge TTS")
    except Exception as e:
        print(f"✗ FAILED")
        print(f"[ERROR] Failed to connect to Edge TTS service: {e}")
        raise
    
    voice_mapping = {
        'indian_english': {'male': None, 'female': None},
        'french_english': {'male': None, 'female': None},
        'chinese_english': {'male': None, 'female': None},
        'spanish_english': {'male': None, 'female': None},
        #'african_english': {'male': None, 'female': None},
        'australian_english': {'male': None, 'female': None},
        'regular_english': {'male': None, 'female': None}
    }
    
    english_voices = [v for v in voices if v['Locale'].startswith('en')]
    spanish_voices = [v for v in voices if 'es-' in v['Locale'].lower()]
    french_voices = [v for v in voices if 'fr-' in v['Locale'].lower()]
    chinese_voices = [v for v in voices if 'zh-' in v['Locale'].lower() or 'cn-' in v['Locale'].lower()]
    
    print(f"\n  📊 Found {len(english_voices)} English voices")
    
    accent_locale_map = {
        'indian_english': {'search_in': 'english', 'locales': ['en-IN']},
        'french_english': {'search_in': 'both', 'locales': ['en-FR', 'fr-FR', 'fr-CA']},
        'chinese_english': {'search_in': 'both', 'locales': ['en-CN', 'zh-CN', 'zh-HK']},
        'spanish_english': {'search_in': 'both', 'locales': ['es-US', 'es-MX', 'en-ES', 'es-ES']},
        #'african_english': {'search_in': 'english', 'locales': ['en-ZA', 'en-NG', 'en-KE']},
        'australian_english': {'search_in': 'english', 'locales': ['en-AU', 'en-GB']},
        'regular_english': {'search_in': 'english', 'locales': ['en-US', 'en-GB', 'en-AU', 'en-CA']}
    }
    
    used_voices = set()
    fallback_count = 0
    
    print("\n  🔗 Mapping voices to accents...")
    
    for accent_key in voice_mapping.keys():
        accent_config = accent_locale_map.get(accent_key, {'search_in': 'english', 'locales': ['en-US']})
        target_locales = accent_config['locales']
        search_in = accent_config['search_in']
        
        if search_in == 'english':
            voice_list = english_voices
        elif search_in == 'both':
            if accent_key == 'spanish_english':
                voice_list = english_voices + spanish_voices
            elif accent_key == 'french_english':
                voice_list = english_voices + french_voices
            elif accent_key == 'chinese_english':
                voice_list = english_voices + chinese_voices
            else:
                voice_list = english_voices
        else:
            voice_list = english_voices
        
        for gender in ['Male', 'Female']:
            voice_found = False
            
            for target_locale in target_locales:
                matching_voices = [
                    v for v in voice_list 
                    if v['Gender'] == gender 
                    and target_locale in v['Locale']
                    and v['ShortName'] not in used_voices
                ]
                
                if accent_key == 'spanish_english' and matching_voices:
                    multilingual = [v for v in matching_voices if 'Multilingual' in v.get('ShortName', '')]
                    if multilingual:
                        matching_voices = multilingual
                
                if matching_voices:
                    selected_voice = matching_voices[0]
                    voice_mapping[accent_key][gender.lower()] = selected_voice['ShortName']
                    used_voices.add(selected_voice['ShortName'])
                    print(f"    ✓ {accent_key:20s} {gender.lower():6s} → {selected_voice['ShortName']:30s} ({selected_voice['Locale']})")
                    voice_found = True
                    break
            
            if not voice_found:
                fallback_voices = [
                    v for v in english_voices 
                    if v['Gender'] == gender 
                    and v['ShortName'] not in used_voices
                ]
                
                if fallback_voices:
                    selected_voice = fallback_voices[0]
                    voice_mapping[accent_key][gender.lower()] = selected_voice['ShortName']
                    used_voices.add(selected_voice['ShortName'])
                    print(f"    ⚠ {accent_key:20s} {gender.lower():6s} → {selected_voice['ShortName']:30s} ({selected_voice['Locale']}) [FALLBACK]")
                    fallback_count += 1
    
    if fallback_count > 0:
        print(f"\n  ⚠ Warning: Used {fallback_count} fallback voices")
    
    # Validate voice mapping
    missing_voices = []
    for accent, genders in voice_mapping.items():
        for gender, voice_name in genders.items():
            if voice_name is None:
                missing_voices.append(f"{accent}/{gender}")
    
    if missing_voices:
        print(f"[WARNING] Missing voices for: {', '.join(missing_voices)}")
    
    print(f"[DEBUG] Voice mapping complete. Mapped {len(voice_mapping)} accents")
    print("")
    return voice_mapping


def discover_voices_google(creds_path=None):
    """Discover available Google TTS voices and map them to our accent/gender requirements"""
    if not GOOGLE_TTS_AVAILABLE:
        raise ImportError("google-cloud-texttospeech is not installed. Install it with: pip install google-cloud-texttospeech")
    
    print("="*60)
    print("🔍 Discovering available Google TTS voices...")
    print("="*60)
    
    # Use explicit credentials if provided
    if creds_path:
        from google.oauth2 import service_account
        creds_path = Path(creds_path)
        if not creds_path.exists():
            raise FileNotFoundError(f"Service account key file not found: {creds_path}")
        credentials = service_account.Credentials.from_service_account_file(str(creds_path))
        print(f"[DEBUG] Using service account credentials: {creds_path}")
    else:
        credentials = None
        print(f"[DEBUG] Using default credentials (GOOGLE_APPLICATION_CREDENTIALS)")
    
    print("  Connecting to Google TTS service...", end=" ", flush=True)
    try:
        if credentials:
            client = texttospeech.TextToSpeechClient(credentials=credentials)
        else:
            client = texttospeech.TextToSpeechClient()
        voices = client.list_voices()
        print(f"✓ Found {len(voices.voices)} total voices")
        print(f"[DEBUG] Successfully retrieved {len(voices.voices)} voices from Google TTS")
    except Exception as e:
        print(f"✗ FAILED")
        print(f"[ERROR] Failed to connect to Google TTS service: {e}")
        if creds_path:
            print(f"[ERROR] Make sure the service account key file exists and has Text-to-Speech API permissions: {creds_path}")
        else:
            print(f"[ERROR] Make sure GOOGLE_APPLICATION_CREDENTIALS is set or credentials are configured")
        raise
    
    voice_mapping = {
        'indian_english': {'male': None, 'female': None},
        'french_english': {'male': None, 'female': None},
        'chinese_english': {'male': None, 'female': None},
        'spanish_english': {'male': None, 'female': None},
        'african_english': {'male': None, 'female': None},
        'regular_english': {'male': None, 'female': None}
    }
    
    # Map accents to Google TTS language codes
    accent_language_map = {
        'indian_english': ['en-IN'],
        'french_english': ['en-GB', 'fr-FR'],  # Using British English or French as fallback
        'chinese_english': ['en-GB', 'zh-CN'],  # Using British English or Chinese as fallback
        'spanish_english': ['en-US', 'es-ES', 'es-US'],  # Using US English or Spanish
        'african_english': ['en-ZA', 'en-GB'],  # South African or British English
        'regular_english': ['en-US', 'en-GB', 'en-AU', 'en-CA']
    }
    
    # Gender mapping
    gender_map = {
        'male': texttospeech.SsmlVoiceGender.MALE,
        'female': texttospeech.SsmlVoiceGender.FEMALE
    }
    
    english_voices = [v for v in voices.voices if v.language_codes and any(lc.startswith('en') for lc in v.language_codes)]
    print(f"\n  📊 Found {len(english_voices)} English voices")
    
    used_voices = set()
    fallback_count = 0
    
    print("\n  🔗 Mapping voices to accents...")
    
    for accent_key in voice_mapping.keys():
        target_languages = accent_language_map.get(accent_key, ['en-US'])
        
        for gender_key, gender_enum in gender_map.items():
            voice_found = False
            
            for target_lang in target_languages:
                matching_voices = [
                    v for v in voices.voices
                    if v.ssml_gender == gender_enum
                    and v.language_codes
                    and (target_lang in v.language_codes or any(lc.startswith(target_lang.split('-')[0]) for lc in v.language_codes))
                    and v.name not in used_voices
                ]
                
                if matching_voices:
                    # Prefer voices that match the exact language code
                    exact_match = [v for v in matching_voices if target_lang in v.language_codes]
                    if exact_match:
                        selected_voice = exact_match[0]
                    else:
                        selected_voice = matching_voices[0]
                    
                    voice_mapping[accent_key][gender_key] = selected_voice.name
                    used_voices.add(selected_voice.name)
                    lang_code = selected_voice.language_codes[0] if selected_voice.language_codes else 'unknown'
                    print(f"    ✓ {accent_key:20s} {gender_key:6s} → {selected_voice.name:30s} ({lang_code})")
                    voice_found = True
                    break
            
            if not voice_found:
                # Fallback to any English voice
                fallback_voices = [
                    v for v in english_voices
                    if v.ssml_gender == gender_enum
                    and v.name not in used_voices
                ]
                
                if fallback_voices:
                    selected_voice = fallback_voices[0]
                    voice_mapping[accent_key][gender_key] = selected_voice.name
                    used_voices.add(selected_voice.name)
                    lang_code = selected_voice.language_codes[0] if selected_voice.language_codes else 'unknown'
                    print(f"    ⚠ {accent_key:20s} {gender_key:6s} → {selected_voice.name:30s} ({lang_code}) [FALLBACK]")
                    fallback_count += 1
    
    if fallback_count > 0:
        print(f"\n  ⚠ Warning: Used {fallback_count} fallback voices")
    
    # Validate voice mapping
    missing_voices = []
    for accent, genders in voice_mapping.items():
        for gender, voice_name in genders.items():
            if voice_name is None:
                missing_voices.append(f"{accent}/{gender}")
    
    if missing_voices:
        print(f"[WARNING] Missing voices for: {', '.join(missing_voices)}")
    
    print(f"[DEBUG] Voice mapping complete. Mapped {len(voice_mapping)} accents")
    print("")
    return voice_mapping


def discover_voices_azure(azure_key=None, azure_region=None):
    """Discover available Azure TTS voices and map them to our accent/gender requirements"""
    if not AZURE_TTS_AVAILABLE:
        raise ImportError("azure-cognitiveservices-speech is not installed. Install it with: pip install azure-cognitiveservices-speech")
    
    if not azure_key or not azure_region:
        raise ValueError("Azure TTS requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION to be set in configuration")
    
    print("="*60)
    print("🔍 Discovering available Azure TTS voices...")
    print("="*60)
    
    print(f"[DEBUG] Using Azure Speech Service: Region={azure_region}")
    print("  Connecting to Azure TTS service...", end=" ", flush=True)
    
    try:
        # Create speech config
        speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
        
        # Create synthesizer to get voices
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)
        
        # Get available voices using REST API (Azure SDK doesn't have direct voice list method)
        import requests
        # Correct endpoint for Azure Speech Service voice list
        url = f"https://{azure_region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        headers = {
            "Ocp-Apim-Subscription-Key": azure_key
        }
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            error_details = response.text if response.text else "No error details"
            raise Exception(f"Failed to fetch voices: {response.status_code} - {error_details}")
        
        voices_data = response.json()
        print(f"✓ Found {len(voices_data)} total voices")
        print(f"[DEBUG] Successfully retrieved {len(voices_data)} voices from Azure TTS")
        
    except Exception as e:
        print(f"✗ FAILED")
        print(f"[ERROR] Failed to connect to Azure TTS service: {e}")
        print(f"[ERROR] Make sure AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are correct")
        raise
    
    voice_mapping = {
        'indian_english': {'male': None, 'female': None},
        'french_english': {'male': None, 'female': None},
        'chinese_english': {'male': None, 'female': None},
        'spanish_english': {'male': None, 'female': None},
        'african_english': {'male': None, 'female': None},
        'regular_english': {'male': None, 'female': None}
    }
    
    # Map accents to Azure TTS locale codes
    # Note: Azure TTS doesn't have "accented English" voices like Edge TTS
    # For French/Spanish/Chinese English, we prioritize non-English voices that might have accent characteristics
    # but these will speak in their native language, not English with accent
    accent_language_map = {
        'indian_english': ['en-IN'],
        'french_english': ['fr-FR', 'fr-CA', 'en-GB'],  # Prioritize French voices first
        'chinese_english': ['zh-CN', 'zh-HK', 'en-GB'],  # Prioritize Chinese voices first
        'spanish_english': ['es-ES', 'es-MX', 'es-US', 'en-US'],  # Prioritize Spanish voices first
        #'african_english': ['en-ZA', 'en-GB'],
        'australian_english': ['en-AU', 'en-GB', 'en-US'],
        'regular_english': ['en-US', 'en-GB', 'en-AU', 'en-CA']
    }
    
    # Gender mapping for Azure
    gender_map = {
        'male': 'Male',
        'female': 'Female'
    }
    
    english_voices = [v for v in voices_data if v.get('Locale', '').startswith('en')]
    print(f"\n  📊 Found {len(english_voices)} English voices")
    
    used_voices = set()
    fallback_count = 0
    
    print("\n  🔗 Mapping voices to accents...")
    
    for accent_key in voice_mapping.keys():
        target_languages = accent_language_map.get(accent_key, ['en-US'])
        
        for gender_key, gender_value in gender_map.items():
            voice_found = False
            
            for target_lang in target_languages:
                # First try exact locale match
                exact_match_voices = [
                    v for v in voices_data
                    if v.get('Gender', '').lower() == gender_value.lower()
                    and v.get('Locale', '') == target_lang
                    and v.get('ShortName') not in used_voices
                ]
                
                if exact_match_voices:
                    selected_voice = exact_match_voices[0]
                    voice_name = selected_voice.get('ShortName', '')
                    voice_mapping[accent_key][gender_key] = voice_name
                    used_voices.add(voice_name)
                    locale = selected_voice.get('Locale', 'unknown')
                    print(f"    ✓ {accent_key:20s} {gender_key:6s} → {voice_name:30s} ({locale})")
                    voice_found = True
                    break
                
                # If no exact match, try prefix match (e.g., 'fr-' for any French locale)
                lang_prefix = target_lang.split('-')[0]
                prefix_match_voices = [
                    v for v in voices_data
                    if v.get('Gender', '').lower() == gender_value.lower()
                    and v.get('Locale', '').startswith(lang_prefix + '-')
                    and v.get('ShortName') not in used_voices
                ]
                
                if prefix_match_voices:
                    selected_voice = prefix_match_voices[0]
                    voice_name = selected_voice.get('ShortName', '')
                    voice_mapping[accent_key][gender_key] = voice_name
                    used_voices.add(voice_name)
                    locale = selected_voice.get('Locale', 'unknown')
                    print(f"    ✓ {accent_key:20s} {gender_key:6s} → {voice_name:30s} ({locale})")
                    voice_found = True
                    break
            
            if not voice_found:
                # Fallback to any English voice
                fallback_voices = [
                    v for v in english_voices
                    if v.get('Gender', '').lower() == gender_value.lower()
                    and v.get('ShortName') not in used_voices
                ]
                
                if fallback_voices:
                    selected_voice = fallback_voices[0]
                    voice_name = selected_voice.get('ShortName', '')
                    voice_mapping[accent_key][gender_key] = voice_name
                    used_voices.add(voice_name)
                    locale = selected_voice.get('Locale', 'unknown')
                    print(f"    ⚠ {accent_key:20s} {gender_key:6s} → {voice_name:30s} ({locale}) [FALLBACK]")
                    fallback_count += 1
    
    if fallback_count > 0:
        print(f"\n  ⚠ Warning: Used {fallback_count} fallback voices")
    
    missing_voices = []
    for accent, genders in voice_mapping.items():
        for gender, voice_name in genders.items():
            if voice_name is None:
                missing_voices.append(f"{accent}/{gender}")
    
    if missing_voices:
        print(f"[WARNING] Missing voices for: {', '.join(missing_voices)}")
    
    print(f"[DEBUG] Voice mapping complete. Mapped {len(voice_mapping)} accents")
    print("")
    return voice_mapping


async def discover_voices(tts_service='google', creds_path=None, azure_key=None, azure_region=None):
    """Discover available voices based on TTS service"""
    tts_service = tts_service.lower()
    
    if tts_service == 'google':
        if not GOOGLE_TTS_AVAILABLE:
            raise ImportError(
                "Google TTS is selected but google-cloud-texttospeech is not installed.\n"
                "Install it with: pip install google-cloud-texttospeech\n"
                "Or set TTS_SERVICE = 'edge' in your configuration file to use Edge TTS instead."
            )
        # Google TTS is synchronous, but we need to run it in executor to avoid blocking
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, discover_voices_google, creds_path)
    elif tts_service == 'azure':
        if not AZURE_TTS_AVAILABLE:
            raise ImportError(
                "Azure TTS is selected but azure-cognitiveservices-speech is not installed.\n"
                "Install it with: pip install azure-cognitiveservices-speech\n"
                "Or set TTS_SERVICE = 'google' or 'edge' in your configuration file."
            )
        # Azure TTS is synchronous, run in executor
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, discover_voices_azure, azure_key, azure_region)
    else:
        return await discover_voices_edge()


async def generate_audio_edge(text, voice_name, output_path):
    """Generate audio file using Edge TTS"""
    try:
        print(f"[DEBUG] Generating audio with voice: {voice_name}")
        print(f"[DEBUG] Text length: {len(text)} characters")
        print(f"[DEBUG] Output path: {output_path}")
        
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(str(output_path))
        
        if not Path(output_path).exists():
            print(f"[ERROR] Audio file was not created: {output_path}")
            return False
        
        file_size = Path(output_path).stat().st_size
        print(f"[DEBUG] Audio file created: {file_size} bytes")
        return True
    except Exception as e:
        print(f"\n      ❌ Error: {str(e)}")
        print(f"[ERROR] Audio generation failed: {type(e).__name__}: {e}")
        return False


def generate_audio_google(text, voice_name, output_path, creds_path=None):
    """Generate audio file using Google TTS"""
    if not GOOGLE_TTS_AVAILABLE:
        raise ImportError("google-cloud-texttospeech is not installed. Install it with: pip install google-cloud-texttospeech")
    
    # Use explicit credentials if provided
    if creds_path:
        from google.oauth2 import service_account
        creds_path = Path(creds_path)
        if not creds_path.exists():
            raise FileNotFoundError(f"Service account key file not found: {creds_path}")
        credentials = service_account.Credentials.from_service_account_file(str(creds_path))
    else:
        credentials = None
    
    try:
        print(f"[DEBUG] Generating audio with voice: {voice_name}")
        print(f"[DEBUG] Text length: {len(text)} characters")
        print(f"[DEBUG] Output path: {output_path}")
        
        if credentials:
            client = texttospeech.TextToSpeechClient(credentials=credentials)
        else:
            client = texttospeech.TextToSpeechClient()
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # Extract language code from voice name (format: languageCode-voiceName)
        # Example: "en-US-Wavenet-D" -> "en-US"
        language_code = 'en-US'  # default
        if '-' in voice_name:
            parts = voice_name.split('-')
            if len(parts) >= 2:
                language_code = f"{parts[0]}-{parts[1]}"
        
        voice = texttospeech.VoiceSelectionParams(
            name=voice_name,
            language_code=language_code
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        output_path = Path(output_path)
        with open(output_path, 'wb') as out:
            out.write(response.audio_content)
        
        if not output_path.exists():
            print(f"[ERROR] Audio file was not created: {output_path}")
            return False
        
        file_size = output_path.stat().st_size
        print(f"[DEBUG] Audio file created: {file_size} bytes")
        return True
    except Exception as e:
        print(f"\n      ❌ Error: {str(e)}")
        print(f"[ERROR] Audio generation failed: {type(e).__name__}: {e}")
        return False


def generate_audio_azure(text, voice_name, output_path, azure_key=None, azure_region=None):
    """Generate audio file using Azure TTS"""
    if not AZURE_TTS_AVAILABLE:
        raise ImportError("azure-cognitiveservices-speech is not installed. Install it with: pip install azure-cognitiveservices-speech")
    
    if not azure_key or not azure_region:
        raise ValueError("Azure TTS requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")
    
    try:
        print(f"[DEBUG] Generating audio with voice: {voice_name}")
        print(f"[DEBUG] Text length: {len(text)} characters")
        print(f"[DEBUG] Output path: {output_path}")
        
        # Create speech config
        speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
        speech_config.speech_synthesis_voice_name = voice_name
        
        # Create synthesizer
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        
        # Synthesize speech
        result = synthesizer.speak_text_async(text).get()
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            # Save audio to file
            output_path = Path(output_path)
            with open(output_path, 'wb') as out:
                out.write(result.audio_data)
            
            if not output_path.exists():
                print(f"[ERROR] Audio file was not created: {output_path}")
                return False
            
            file_size = output_path.stat().st_size
            print(f"[DEBUG] Audio file created: {file_size} bytes")
            return True
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation = speechsdk.CancellationDetails(result)
            error_msg = f"Azure TTS canceled: {cancellation.reason}"
            if cancellation.reason == speechsdk.CancellationReason.Error:
                error_msg += f" - {cancellation.error_details}"
            print(f"\n      ❌ Error: {error_msg}")
            print(f"[ERROR] Audio generation failed: {error_msg}")
            return False
        else:
            error_msg = f"Azure TTS failed: {result.reason}"
            print(f"\n      ❌ Error: {error_msg}")
            print(f"[ERROR] Audio generation failed: {error_msg}")
            return False
            
    except Exception as e:
        print(f"\n      ❌ Error: {str(e)}")
        print(f"[ERROR] Audio generation failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def generate_audio(text, voice_name, output_path, tts_service='google', creds_path=None, azure_key=None, azure_region=None):
    """Generate audio file using specified TTS service"""
    tts_service = tts_service.lower()
    
    if tts_service == 'google':
        # Google TTS is synchronous, run it in executor to avoid blocking
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, generate_audio_google, text, voice_name, output_path, creds_path)
    elif tts_service == 'azure':
        # Azure TTS is synchronous, run it in executor
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, generate_audio_azure, text, voice_name, output_path, azure_key, azure_region)
    else:
        return await generate_audio_edge(text, voice_name, output_path)


def convert_to_dialogflow_format(input_path, output_path):
    """Convert audio to Dialogflow-compatible format (16kHz, mono, 16-bit PCM WAV)"""
    try:
        input_path = Path(input_path)
        output_path = Path(output_path)
        
        if not input_path.exists():
            print(f"[ERROR] Input file does not exist: {input_path}")
            return False
        
        print(f"[DEBUG] Converting audio: {input_path.name} -> {output_path.name}")
        print(f"[DEBUG] Using {'pydub' if USE_PYDUB else 'soundfile'} for conversion")
        
        if USE_PYDUB:
            print(f"[DEBUG] Loading audio with pydub...")
            print('input path is ********************************************$$$$$$$$$$$$$$')
            print(str(input_path))
            audio = AudioSegment.from_file(str(input_path))
            #audio= AudioSegment.from_file('C:\\PythonDevelopment\\AdkTest\\SteeringPolicyBot\\utteranceVersionTwo-main\\BiasTestingForBots\\code\\audio-service\\test-output\\original\\utterance_1\\1_male_indian_english.mp3')
            print('Failed here ********************************************$$$$$$$$$$$$$$')
            print(f"[DEBUG] Original: {audio.channels} channels, {audio.frame_rate}Hz, {audio.sample_width*8}bit")
            
            if audio.channels > 1:
                print(f"[DEBUG] Converting to mono...")
                audio = audio.set_channels(1)
            if audio.frame_rate != 16000:
                print(f"[DEBUG] Resampling to 16kHz...")
                audio = audio.set_frame_rate(16000)
            if audio.sample_width != 2:
                print(f"[DEBUG] Setting sample width to 16-bit...")
                audio = audio.set_sample_width(2)
            
            print(f"[DEBUG] Exporting to WAV...")
            audio.export(str(output_path), format="wav")
        else:
            import soundfile as sf
            import numpy as np
            from scipy import signal
            
            print(f"[DEBUG] Loading audio with soundfile...")
            data, sample_rate = sf.read(str(input_path))
            print(f"[DEBUG] Original: {sample_rate}Hz, shape: {data.shape}, dtype: {data.dtype}")
            
            if len(data.shape) > 1 and data.shape[1] > 1:
                print(f"[DEBUG] Converting stereo to mono...")
                data = np.mean(data, axis=1)
            
            if sample_rate != 16000:
                print(f"[DEBUG] Resampling from {sample_rate}Hz to 16000Hz...")
                num_samples = int(len(data) * 16000 / sample_rate)
                data = signal.resample(data, num_samples)
            
            if data.dtype != np.int16:
                print(f"[DEBUG] Converting to 16-bit PCM...")
                max_val = np.abs(data).max()
                if max_val > 0:
                    data = data / max_val
                data = (data * 32767).astype(np.int16)
            
            print(f"[DEBUG] Writing WAV file...")
            sf.write(str(output_path), data, 16000, subtype='PCM_16', format='WAV')
        
        if not output_path.exists():
            print(f"[ERROR] Output file was not created: {output_path}")
            return False
        
        output_size = output_path.stat().st_size
        print(f"[DEBUG] Conversion complete: {output_size} bytes")
        return True
    except Exception as e:
        print(f"\n      ❌ Conversion error: {str(e)}")
        print(f"[ERROR] Audio conversion failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def generate_utterance_variations(utterance_id, utterance_text, voice_map, original_dir, dialogflow_dir, tts_service='google', creds_path=None, azure_key=None, azure_region=None):
    """Generate all 12 variations for a single utterance"""
    results = []
    total_variations = len(ACCENTS) * len(GENDERS)
    current_file = 0
    
    print(f"  Generating {total_variations} voice variations (6 accents × 2 genders)...")
    print(f"  Utterance ID: {utterance_id}")
    print(f"  Text: '{utterance_text}'")
    print(f"  TTS Service: {tts_service.upper()}")
    print("")
    
    for accent in ACCENTS:
        for gender in GENDERS:
            current_file += 1
            voice_name = voice_map.get(accent, {}).get(gender)
            
            if not voice_name:
                print(f"  [{current_file}/{total_variations}] ⚠ SKIPPED: {accent.upper()} {gender.upper()}")
                continue
            
            utterance_dir = original_dir / f"utterance_{utterance_id}"
            utterance_dir.mkdir(parents=True, exist_ok=True)
            
            df_dir = dialogflow_dir / f"utterance_{utterance_id}"
            df_dir.mkdir(parents=True, exist_ok=True)
            
            original_file = utterance_dir / f"{utterance_id}_{gender}_{accent}.mp3"
            dialogflow_file = df_dir / f"{utterance_id}_{gender}_{accent}.wav"
            
            print(f"  [{current_file}/{total_variations}] 🎤 {accent.upper()} {gender.upper()}")
            print(f"      Voice: {voice_name}")
            print(f"      Creating audio...", end=" ", flush=True)
            
            success = await generate_audio(utterance_text, voice_name, original_file, tts_service, creds_path, azure_key, azure_region)
            
            if success:
                file_size_kb = original_file.stat().st_size / 1024
                print(f"✓ ({file_size_kb:.1f} KB)")
                
                print(f"      Converting...", end=" ", flush=True)
                convert_success = convert_to_dialogflow_format(original_file, dialogflow_file)
                
                if convert_success:
                    df_size_kb = dialogflow_file.stat().st_size / 1024
                    print(f"✓ ({df_size_kb:.1f} KB)")
                    print(f"      ✓ Saved: {dialogflow_file.name}")
                    print("")
                    
                    results.append({
                        'utterance_id': utterance_id,
                        'accent': accent,
                        'gender': gender,
                        'voice': voice_name,
                        'original_file': str(original_file),
                        'dialogflow_file': str(dialogflow_file),
                        'status': 'success'
                    })
                else:
                    print(f"✗ FAILED")
                    results.append({
                        'utterance_id': utterance_id,
                        'accent': accent,
                        'gender': gender,
                        'status': 'conversion_failed'
                    })
            else:
                print(f"✗ FAILED")
                results.append({
                    'utterance_id': utterance_id,
                    'accent': accent,
                    'gender': gender,
                    'status': 'generation_failed'
                })
    
    successful = len([r for r in results if r['status'] == 'success'])
    print(f"  ✓ Completed: {successful}/{total_variations} files generated")
    print("")
    
    return results


async def process_excel_file(excel_path, output_dir, limit=None, tts_service='google', creds_path=None, azure_key=None, azure_region=None):
    """Process Excel file and generate audio files"""
    # Read Excel file
    print("="*60)
    print("📄 LOADING EXCEL FILE")
    print("="*60)
    
    try:
        excel_path = Path(excel_path)
        print(f"  Reading: {excel_path}")
        print(f"[DEBUG] Excel file exists: {excel_path.exists()}")
        print(f"[DEBUG] Excel file size: {excel_path.stat().st_size if excel_path.exists() else 'N/A'} bytes")
        
        df = pd.read_excel(excel_path, sheet_name=0)
        print(f"  ✓ Loaded successfully")
        print(f"  Total rows: {len(df)}")
        print(f"[DEBUG] Excel columns: {list(df.columns)}")
        
        if 'Utterance' not in df.columns:
            print("  ❌ Error: 'Utterance' column not found")
            print(f"[ERROR] Available columns: {list(df.columns)}")
            return None
        
        valid_df = df[df['Utterance'].notna() & (df['Utterance'].astype(str).str.strip() != '')]
        print(f"[DEBUG] Valid utterances after filtering: {len(valid_df)}")
        
        if limit and limit > 0:
            print(f"[DEBUG] Applying limit: {limit}")
            valid_df = valid_df.head(limit)
            print(f"\n  ⚠ Limited to {len(valid_df)} utterance(s) (--limit={limit})")
        
        print(f"  Valid utterances: {len(valid_df)}")
        print(f"  Expected audio files: {len(valid_df) * 12} (12 per utterance)")
    except Exception as e:
        print(f"  ❌ Error reading Excel file: {e}")
        print(f"[ERROR] Excel file reading failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Discover voices
    print("\n" + "="*60)
    try:
        voice_map = await discover_voices(tts_service, creds_path, azure_key, azure_region)
        
        if not voice_map:
            print("[ERROR] Voice mapping is empty")
            return None
        
        # Save voice mapping
        mapping_file = output_dir / 'voice_mapping.json'
        print(f"[DEBUG] Saving voice mapping to: {mapping_file}")
        try:
            with open(mapping_file, 'w') as f:
                json.dump(voice_map, f, indent=2)
            print(f"[DEBUG] Voice mapping saved successfully")
        except Exception as save_error:
            print(f"[WARNING] Failed to save voice mapping: {save_error}")
    except Exception as e:
        print(f"[ERROR] Voice discovery failed: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Generate audio files
    print("\n" + "="*60)
    print("🎵 GENERATING AUDIO FILES")
    print("="*60)
    
    original_dir = output_dir / 'original'
    dialogflow_dir = output_dir / 'dialogflow-ready'
    
    all_results = []
    current_utterance = 0
    total_utterances = len(valid_df)
    
    for idx, row in valid_df.iterrows():
        utterance_id = current_utterance + 1
        utterance_text = str(row['Utterance']).strip()
        
        if not utterance_text or utterance_text.lower() == 'nan':
            continue
        
        current_utterance += 1
        print("\n" + "="*60)
        print(f"📝 UTTERANCE {utterance_id}/{total_utterances}")
        print("="*60)
        print(f"Text: '{utterance_text}'")
        print("")
        
        results = await generate_utterance_variations(
            utterance_id, utterance_text, voice_map, original_dir, dialogflow_dir, tts_service, creds_path, azure_key, azure_region
        )
        all_results.extend(results)
        
        successful = len([r for r in results if r['status'] == 'success'])
        print(f"✓ Utterance {utterance_id} complete: {successful}/12 files")
        print(f"  Progress: {current_utterance}/{total_utterances} utterances")
        print("")
    
    # Save results
    results_df = pd.DataFrame(all_results)
    results_file = output_dir / 'tts_generation_results.csv'
    results_df.to_csv(results_file, index=False)
    
    successful_count = len([r for r in all_results if r['status'] == 'success'])
    
    return {
        'total_files': successful_count,
        'total_expected': len(valid_df) * 12,
        'utterances_processed': len(valid_df),
        'results': all_results,
        'voice_mapping': voice_map,
        'audio_directory': str(dialogflow_dir)
    }


def generate_audio_files(excel_path, output_dir, limit=None, tts_service='google', creds_path=None, azure_key=None, azure_region=None):
    """Main function to generate audio files - synchronous wrapper"""
    excel_path = Path(excel_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    return asyncio.run(process_excel_file(excel_path, output_dir, limit, tts_service, creds_path, azure_key, azure_region))

