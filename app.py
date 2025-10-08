from fastapi import FastAPI, UploadFile, File
import uvicorn
from name_extractor import extract_patient_name

app = FastAPI()

@app.post("/extract-name/")
async def get_patient_name(file: UploadFile = File(...)):
    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    name, source = extract_patient_name(file_path, original_filename=file.filename)

    return {"patient_name": name, "source": source}

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
