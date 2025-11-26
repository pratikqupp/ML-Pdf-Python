#!/usr/bin/env python3
import imaplib
import email
from email.header import decode_header
from email.message import Message
import json
import os
import tempfile
import traceback
import time
import requests
from typing import Dict, Any, Optional
import concurrent.futures
import logging
import ssl  # For SSLEOFError
import re

from playwright.sync_api import sync_playwright

# ===========================
# 🔧 Configuration
# ===========================
CONFIG_PATH = "config.json"
API_UPLOAD_URL = "https://toplabsbazaardev-git-development-pratiks-projects-7c12a0c0.vercel.app/booking-services/upload-report"

# NEW: Batch size to reduce requests to the IMAP server
BATCH_SIZE = 20

# ===========================
# 🪵 Logging
# ===========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
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


def decode_str(s) -> str:
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


def extract_thyrocare_link_from_email(msg: Message, logger: logging.Logger) -> Optional[str]:
    """
    Look through all text/plain and text/html parts and extract
    a Thyrocare report link like: https://thyro.care/n/o/0XTN0v
    """
    body_texts = []

    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue

        try:
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")
            body_texts.append(text)
        except Exception as e:
            logger.debug(f"Failed to decode part body: {e}")
            continue

    if not body_texts:
        return None

    full_body = "\n".join(body_texts)

    # Regex to find the Thyrocare link
    m = re.search(r"https://thyro\.care/n/o/[^\s\"'<>]+", full_body)
    if m:
        return m.group(0)

    return None


def fetch_thyrocare_pdf_playwright(thyro_url: str, logger: logging.Logger) -> str:
    """
    Use headless Chromium via Playwright to:
      - open Thyrocare URL
      - click 'Download Report'
      - wait for the PDF download

    Returns path to a temporary PDF file.
    """
    logger.info(f"[THYROCARE] Launching browser for URL: {thyro_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        page.goto(thyro_url, wait_until="networkidle", timeout=60000)

        logger.info("[THYROCARE] Page loaded, clicking 'Download Report'...")

        # Wait for download event
        with page.expect_download(timeout=60000) as download_info:
            page.click("text=Download Report")
        download = download_info.value

        suggested_name = download.suggested_filename or f"thyrocare-report-{int(time.time())}.pdf"
        fd, temp_path = tempfile.mkstemp(prefix="thyro_", suffix=".pdf")
        os.close(fd)

        download.save_as(temp_path)
        logger.info(f"[THYROCARE] Report downloaded to {temp_path}")

        context.close()
        browser.close()

        return temp_path


# ===========================
# ☁️ API Upload
# ===========================
def upload_report_to_api(file_path: str, patient_name: str, logger: logging.Logger):
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/pdf")}
            data = {"patientName": patient_name}
            response = requests.post(API_UPLOAD_URL, files=files, data=data)

        if response.status_code == 200:
            logger.info(f"[UPLOAD ✅] Uploaded {file_path} for '{patient_name}'")
        else:
            logger.error(f"[UPLOAD ❌] Failed ({response.status_code}): {response.text}")
    except Exception as e:
        logger.error(f"[UPLOAD ❌] Error uploading {file_path}: {e}")


# ===========================
# 📬 Mail Processing
# ===========================
def process_account(account: Dict[str, Any], processed_ids: set, max_emails: int):
    """
    Connects to a single IMAP account, fetches new emails in batches,
    processes attachments and Thyrocare links, and uploads them.
    """
    name = account.get("name") or account["email"]
    imap_server = account["imap_server"]
    imap_port = account.get("imap_port", 993)
    user = account["email"]
    password = account["password"]

    logger = logging.getLogger(name)

    logger.info(f"Connecting to {imap_server} ...")
    try:
        imap = imaplib.IMAP4_SSL(imap_server, imap_port)
        imap.login(user, password)
    except Exception as e:
        logger.error(f"IMAP login failed: {e}")
        return

    try:
        imap.select("INBOX")
        result, data = imap.uid('search', None, "ALL")
        if result != 'OK':
            logger.error("UID search failed")
            return

        uids = sorted([int(x) for x in data[0].split()], reverse=True)
        latest_uids = uids[:max_emails]

        if not latest_uids:
            logger.info("No emails found to process.")
            return

        logger.info(f"Found {len(latest_uids)} emails to check.")

        # --- BATCH PROCESSING ---
        for i in range(0, len(latest_uids), BATCH_SIZE):
            batch_uids = latest_uids[i:i + BATCH_SIZE]
            uid_str = ",".join(str(u) for u in batch_uids)
            logger.info(
                f"Fetching batch {i // BATCH_SIZE + 1}/"
                f"{(len(latest_uids) - 1) // BATCH_SIZE + 1} "
                f"(UIDs {batch_uids[0]}...{batch_uids[-1]})"
            )

            msg_data = []
            try:
                res, msg_data = imap.uid('fetch', uid_str, '(RFC822)')
            except (imaplib.IMAP4.abort, ssl.SSLEOFError, imaplib.IMAP4.error) as e_conn:
                logger.error(f"Connection error on batch fetch: {e_conn}. Aborting this run.")
                traceback.print_exc()
                break

            if res != 'OK' or not msg_data:
                logger.error("Failed to fetch batch.")
                continue

            messages_in_batch = [item for item in msg_data if isinstance(item, tuple)]

            batch_connection_error = False

            for msg_tuple in messages_in_batch:
                uid_from_header = -1
                try:
                    uid_from_header = int(msg_tuple[0].decode('utf-8').split(' ')[0])
                    raw = msg_tuple[1]
                    msg = email.message_from_bytes(raw)
                    message_id = msg.get("Message-ID") or str(uid_from_header)

                    if message_id in processed_ids:
                        continue  # Skip already processed

                    frm = decode_str(msg.get("From", ""))
                    subject = decode_str(msg.get("Subject", ""))
                    logger.info(f"Processing UID {uid_from_header}, From: {frm}, Subject: {subject}")

                    processed_any_pdf = False  # track if we handled a PDF attachment

                    # ---------- 1) Normal PDF attachments ----------
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart':
                            continue
                        filename = get_filename_from_part(part)
                        if not filename or not filename.lower().endswith(".pdf"):
                            continue

                        payload = part.get_payload(decode=True)
                        if not payload:
                            continue

                        processed_any_pdf = True

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

                            logger.info(
                                f"Attachment '{filename}' -> extracted: '{extracted_name}' (source: {source})"
                            )
                            upload_report_to_api(temp_path, extracted_name, logger)

                        except Exception as ex_proc:
                            logger.error(f"Error processing attachment {filename}: {ex_proc}")
                            traceback.print_exc()
                        finally:
                            try:
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)
                            except Exception as del_err:
                                logger.error(f"[CLEANUP ❌] Failed to delete {temp_path}: {del_err}")

                    # ---------- 2) No PDF attachments? Try Thyrocare link ----------
                    if not processed_any_pdf:
                        thyro_link = extract_thyrocare_link_from_email(msg, logger)
                        if thyro_link:
                            logger.info(f"[THYROCARE] Detected Thyrocare link: {thyro_link}")
                            temp_path = None
                            try:
                                temp_path = fetch_thyrocare_pdf_playwright(thyro_link, logger)

                                try:
                                    from name_extractor import extract_patient_name
                                except Exception:
                                    extract_patient_name = globals().get("extract_patient_name")
                                    if not extract_patient_name:
                                        raise RuntimeError("extract_patient_name function not available.")

                                res_name = extract_patient_name(
                                    temp_path,
                                    original_filename="thyrocare-report.pdf"
                                )
                                if isinstance(res_name, tuple):
                                    extracted_name, source = res_name
                                else:
                                    extracted_name = res_name
                                    source = "ml"

                                logger.info(
                                    f"[THYROCARE] Extracted name '{extracted_name}' "
                                    f"(source: {source}) from fetched PDF"
                                )
                                upload_report_to_api(temp_path, extracted_name, logger)

                            except Exception as ex_thyro:
                                logger.error(f"[THYROCARE ❌] Error processing Thyrocare link: {ex_thyro}")
                                traceback.print_exc()
                            finally:
                                if temp_path and os.path.exists(temp_path):
                                    try:
                                        os.remove(temp_path)
                                    except Exception as del_err:
                                        logger.error(
                                            f"[THYROCARE CLEANUP ❌] Failed to delete {temp_path}: {del_err}"
                                        )

                    # ---------- 3) Mark email as seen & processed ----------
                    imap.uid('store', str(uid_from_header), '+FLAGS', '(\\Seen)')
                    processed_ids.add(message_id)

                except (imaplib.IMAP4.abort, ssl.SSLEOFError, imaplib.IMAP4.error) as e_conn:
                    logger.error(
                        f"Connection error storing/processing UID {uid_from_header}: {e_conn}. "
                        f"Aborting this run."
                    )
                    traceback.print_exc()
                    batch_connection_error = True
                    break

                except Exception as e_item:
                    logger.error(f"Error on UID {uid_from_header}: {e_item}")
                    traceback.print_exc()

            if batch_connection_error:
                break

            # polite sleep between batches
            time.sleep(1)

    finally:
        try:
            imap.logout()
            logger.info("Connection closed.")
        except Exception as e_logout:
            logger.info(f"Logout failed (connection likely already closed): {e_logout}")


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

    root_logger = logging.getLogger()
    root_logger.info(
        f"📬 Mail processor started with {len(accounts)} account(s), "
        f"{max_threads} thread(s)"
    )

    try:
        while True:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = [
                    executor.submit(process_account, acc, processed_ids, max_emails)
                    for acc in accounts
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        root_logger.exception(f"Thread execution error: {e}")

            root_logger.info("Run complete. Saving state...")
            save_state(state_file, processed_ids)
            root_logger.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)

    except KeyboardInterrupt:
        root_logger.info("🛑 Graceful shutdown requested...")
        save_state(state_file, processed_ids)
        root_logger.info("✅ State saved. Bye!")


# ===========================
# 🚀 Entry Point
# ===========================
if __name__ == "__main__":
    main_loop()
