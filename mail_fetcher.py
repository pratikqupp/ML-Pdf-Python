#!/usr/bin/env python3
import imaplib
import email
from email.header import decode_header
import json
import os
import tempfile
import traceback
import time
from typing import Dict, Any, Optional
import requests  # 🆕 added

CONFIG_PATH = "config.json"
STATE_FILE = "state.json"

# 🆕 your Node API URL
API_UPLOAD_URL = "https://toplabsbazaardev-git-development-pratiks-projects-7c12a0c0.vercel.app/booking-services/upload-report"

# ---------- HELPERS ----------
def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_state() -> set:
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))

def save_state(state: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(state), f, indent=2)

def decode_str(s: Optional[bytes]) -> str:
    if not s:
        return ""
    if isinstance(s, str):
        return s
    try:
        parts = decode_header(s)
        pieces = []
        for part, enc in parts:
            if isinstance(part, bytes):
                pieces.append(part.decode(enc or "utf-8", errors="ignore"))
            else:
                pieces.append(part)
        return "".join(pieces)
    except Exception:
        return str(s)

def get_filename_from_part(part) -> str:
    fname = part.get_filename()
    return decode_str(fname) if fname else ""

def upload_report_to_api(file_path: str, patient_name: str):
    try:
        with open(file_path, "rb") as f:
            files = {"pdf": (os.path.basename(file_path), f, "application/pdf")}
            data = {"name": patient_name}
            response = requests.post(API_UPLOAD_URL, files=files, data=data)
        if response.status_code == 200:
            print(f"[UPLOAD ✅] Uploaded {file_path} for '{patient_name}'")
        else:
            print(f"[UPLOAD ❌] Failed ({response.status_code}): {response.text}")
    except Exception as e:
        print(f"[UPLOAD ❌] Error uploading {file_path}: {e}")

# ---------- MAIN PROCESSING ----------
def process_account(account: Dict[str, Any], processed_ids: set):
    name = account.get("name") or account["email"]
    imap_server = account["imap_server"]
    imap_port = account.get("imap_port", 993)
    user = account["email"]
    password = account["password"]

    print(f"[{name}] Connecting to {imap_server} ...")
    try:
        imap = imaplib.IMAP4_SSL(imap_server, imap_port)
        imap.login(user, password)
    except Exception as e:
        print(f"[{name}] IMAP login failed: {e}")
        return

    try:
        imap.select("INBOX")
        result, data = imap.uid('search', None, "ALL")
        if result != 'OK':
            print(f"[{name}] UID search failed")
            imap.logout()
            return

        uids = sorted([int(x) for x in data[0].split()], reverse=True)
        latest_uids = uids[:10]  # only latest 10

        for uid in latest_uids:
            try:
                res, msg_data = imap.uid('fetch', str(uid), '(RFC822)')
                if res != 'OK' or not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                message_id = msg.get("Message-ID") or str(uid)

                if message_id in processed_ids:
                    continue

                frm = decode_str(msg.get("From", ""))
                subject = decode_str(msg.get("Subject", ""))
                print(f"[{name}] Processing UID {uid}, Message-ID {message_id}, From: {frm}, Subject: {subject}")

                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    filename = get_filename_from_part(part)
                    if not filename or not filename.lower().endswith(".pdf"):
                        continue
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    # 🆕 create temp file
                    with tempfile.NamedTemporaryFile(prefix="rep_", suffix=".pdf", delete=False) as tf:
                        tf.write(payload)
                        temp_path = tf.name

                    try:
                        try:
                            from name_extractor import extract_patient_name
                        except Exception:
                            extract_patient_name = globals().get("extract_patient_name")
                            if not extract_patient_name:
                                raise RuntimeError("extract_patient_name function not available.")

                        res = extract_patient_name(temp_path, original_filename=filename)
                        if isinstance(res, tuple):
                            extracted_name, source = res
                        else:
                            extracted_name = res
                            source = "filename"

                        print(f"[{name}] Attachment '{filename}' -> extracted: '{extracted_name}' (source: {source})")

                        # 🆕 Upload file & name to API
                        upload_report_to_api(temp_path, extracted_name)

                    except Exception as ex_proc:
                        print(f"[{name}] Error processing attachment {filename}: {ex_proc}")
                        traceback.print_exc()
                    finally:
                        # 🧹 Always delete temp file
                        try:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                                print(f"[CLEANUP 🧹] Deleted temp file: {temp_path}")
                        except Exception as del_err:
                            print(f"[CLEANUP ❌] Failed to delete temp file {temp_path}: {del_err}")

                imap.uid('store', str(uid), '+FLAGS', '(\\Seen)')
                processed_ids.add(message_id)
                time.sleep(0.1)

            except Exception as e_item:
                print(f"[{name}] Error UID {uid}: {e_item}")
                traceback.print_exc()

        imap.logout()
    except Exception as e_main:
        print(f"[{name}] Error in mailbox processing: {e_main}")
        traceback.print_exc()
        try:
            imap.logout()
        except Exception:
            pass

# ---------- RUNNER ----------
def main_loop():
    cfg = load_config(CONFIG_PATH)
    interval = cfg.get("poll_interval_seconds", 30)
    processed_ids = load_state()

    while True:
        for account in cfg.get("accounts", []):
            process_account(account, processed_ids)
        save_state(processed_ids)
        time.sleep(interval)

if __name__ == "__main__":
    main_loop()
