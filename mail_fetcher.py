#!/usr/bin/env python3
import imaplib
import email
from email.header import decode_header
import json
import os
import tempfile
import traceback
import time
import requests
from typing import Dict, Any, Optional
import concurrent.futures
import logging

# ===========================
# 🔧 Configuration
# ===========================
CONFIG_PATH = "config.json"
API_UPLOAD_URL = "https://toplabsbazaardev-git-development-pratiks-projects-7c12a0c0.vercel.app/booking-services/upload-report"

# ===========================
# 🪵 Logging
# ===========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

# ===========================
# 🧰 Helpers
# ===========================
def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_state(state_file: str) -> set:
    if not os.path.exists(state_file):
        return set()
    with open(state_file, "r", encoding="utf-8") as f:
        return set(json.load(f))

def save_state(state_file: str, state: set):
    with open(state_file, "w", encoding="utf-8") as f:
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

# ===========================
# ☁️ API Upload
# ===========================
def upload_report_to_api(file_path: str, patient_name: str):
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/pdf")}
            data = {"patientName": patient_name}
            response = requests.post(API_UPLOAD_URL, files=files, data=data)

        if response.status_code == 200:
            logging.info(f"[UPLOAD ✅] Uploaded {file_path} for '{patient_name}'")
        else:
            logging.error(f"[UPLOAD ❌] Failed ({response.status_code}): {response.text}")
    except Exception as e:
        logging.error(f"[UPLOAD ❌] Error uploading {file_path}: {e}")

# ===========================
# 📬 Mail Processing
# ===========================
def process_account(account: Dict[str, Any], processed_ids: set, max_emails: int):
    name = account.get("name") or account["email"]
    imap_server = account["imap_server"]
    imap_port = account.get("imap_port", 993)
    user = account["email"]
    password = account["password"]

    logging.info(f"[{name}] Connecting to {imap_server} ...")
    try:
        imap = imaplib.IMAP4_SSL(imap_server, imap_port)
        imap.login(user, password)
    except Exception as e:
        logging.error(f"[{name}] IMAP login failed: {e}")
        return

    try:
        imap.select("INBOX")
        result, data = imap.uid('search', None, "ALL")
        if result != 'OK':
            logging.error(f"[{name}] UID search failed")
            imap.logout()
            return

        uids = sorted([int(x) for x in data[0].split()], reverse=True)
        latest_uids = uids[:max_emails]

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
                logging.info(f"[{name}] Processing UID {uid}, From: {frm}, Subject: {subject}")

                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    filename = get_filename_from_part(part)
                    if not filename or not filename.lower().endswith(".pdf"):
                        continue
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

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

                        res_name = extract_patient_name(temp_path, original_filename=filename)
                        if isinstance(res_name, tuple):
                            extracted_name, source = res_name
                        else:
                            extracted_name = res_name
                            source = "filename"

                        logging.info(f"[{name}] Attachment '{filename}' -> extracted: '{extracted_name}' (source: {source})")

                        upload_report_to_api(temp_path, extracted_name)

                    except Exception as ex_proc:
                        logging.error(f"[{name}] Error processing attachment {filename}: {ex_proc}")
                        traceback.print_exc()
                    finally:
                        try:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                                logging.info(f"[CLEANUP 🧹] Deleted temp file: {temp_path}")
                        except Exception as del_err:
                            logging.error(f"[CLEANUP ❌] Failed to delete {temp_path}: {del_err}")

                imap.uid('store', str(uid), '+FLAGS', '(\\Seen)')
                processed_ids.add(message_id)
                time.sleep(0.1)

            except Exception as e_item:
                logging.error(f"[{name}] Error UID {uid}: {e_item}")
                traceback.print_exc()

    finally:
        imap.logout()

# ===========================
# 🧵 Threaded Main Loop
# ===========================
def main_loop():
    cfg = load_config(CONFIG_PATH)
    interval = cfg.get("poll_interval_seconds", 30)
    state_file = cfg.get("state_file", "state.json")
    max_emails = cfg.get("max_emails_per_run", 50)
    accounts = cfg.get("accounts", [])

    processed_ids = load_state(state_file)
    max_threads = min(5, len(accounts)) or 1

    logging.info(f"📬 Mail processor started with {len(accounts)} account(s), {max_threads} thread(s)")

    try:
        while True:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = [executor.submit(process_account, acc, processed_ids, max_emails) for acc in accounts]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logging.exception(f"Thread execution error: {e}")

            save_state(state_file, processed_ids)
            time.sleep(interval)

    except KeyboardInterrupt:
        logging.info("🛑 Graceful shutdown requested...")
        save_state(state_file, processed_ids)
        logging.info("✅ State saved. Bye!")

# ===========================
# 🚀 Entry Point
# ===========================
if __name__ == "__main__":
    main_loop()
