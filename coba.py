import streamlit as st
import cv2
import pytesseract
import numpy as np
import re
import pandas as pd 
import os
import requests
from rapidfuzz import process, fuzz

# --- 1. HARUS PALING ATAS (SETELAH IMPORT) ---
st.set_page_config(page_title="Halal & Allergen Scanner", layout="centered")

# --- CONFIG TESSERACT ---
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

if os.name == 'nt': 
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- 2. FUNGSI DASAR ---
def clean_text(text):
    if not text or pd.isna(text):
        return ""
    text = str(text).lower()
    garbage_phrases = [
        r'cetak tebal.*', r'komposise', r'a es', r'mengandung alergen.*', 
        r'tanpa bahan pengawet.*', r'tanpa penguat rasa.*', 
        r'tanpa pemanis buatan.*', r'komposisi', r'komposis', 
        r'mungkin mengandung.*', r'ingredients*'
    ]
    for phrase in garbage_phrases:
        text = re.sub(phrase, '', text)
    text = text.replace('(', ',').replace(')', ',')
    text = re.sub(r'(\d)\.(\d)', r'\1DOT\2', text)
    text = text.replace('.', ',')
    text = text.replace('DOT', '.')
    text = re.sub(r'[^a-z0-9,\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s*,\s*', ',', text)
    return text

def extract_ingredients(text):
    if not text:
        return []
    ingredients = text.split(',')
    return [ing.strip() for ing in ingredients if ing.strip() != ""]

# --- 3. DICTIONARY DATA ---
allergen_dict = {
    "Susu": ["milk", "whole milk", "skim milk", "milk powder", "whey", "lactose", "butter", "cream", "cheese", "susu", "lemak susu", "mentega", "keju"],
    "Telur": ["egg", "egg powder", "egg white", "egg yolk", "albumin", "telur", "putih telur"],
    "Ikan": ["fish", "ikan", "anchovy", "tuna", "salmon"],
    "Krustasea & Moluska": ["shrimp", "prawn", "crab", "lobster", "squid", "udang", "kepiting", "cumi"],
    "Kacang Tanah": ["peanut", "kacang tanah", "minyak kacang"],
    "Kacang Pohon": ["almond", "walnut", "cashew", "mete"],
    "Gandum & Gluten": ["wheat", "flour", "gluten", "gandum", "terigu", "malt"],
    "Kedelai": ["soy", "soya", "soybean", "lecithin", "kedelai", "tempe", "tahu"],
    "Wijen": ["sesame", "wijen"],
    "Sulfit": ["sulfite", "sulphite", "sulfit"]
}

NON_HALAL = {"pork", "pig", "swine", "lard", "bacon", "ham", "porcine", "alcohol", "ethanol", "wine", "beer", "rum", "whisky", "blood", "anjing"}

CRITICAL_HALAL = {
    "gelatin", "enzyme", "rennet", "pepsin", "lipase", "protease", "maltodextrin",
    "mono diglyceride", "e471", "e472", "e473", "e477", "shortening", "collagen",
    "flavor", "flavour", "acidity regulator", "synthetic food colour", "glycerin", "stearate"
}

# --- 4. LOAD DATA SEKUNDER ---
@st.cache_data
def load_all_master_ingredients():
    url = "https://raw.githubusercontent.com/deayulianis/coba-skripsi/refs/heads/main/komposisi.json"
    master_set = set()
    try:
        df_sekunder = pd.read_json(url)
        for val in df_sekunder[0]:
            if pd.notna(val):
                cleaned_val = clean_text(str(val))
                master_set.update(extract_ingredients(cleaned_val))
    except Exception as e:
        pass # Diamkan agar tidak memicu perintah UI Streamlit sebelum waktunya

    master_set.update(NON_HALAL)
    master_set.update(CRITICAL_HALAL)
    for keywords in allergen_dict.values():
        master_set.update(keywords)
    return list(master_set)

MASTER_INGREDIENTS = load_all_master_ingredients()

# --- 5. LOGIKA ANALISIS ---
def normalize_ingredient(ingredient):
    numbers = re.findall(r'\d+\.?\d*%?', ingredient)
    clean_name = re.sub(r'\d+\.?\d*%?', '', ingredient).strip()
    if not clean_name: return ingredient
    match = process.extractOne(clean_name, MASTER_INGREDIENTS, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= 80:
        result_name = match[0]
        return f"{result_name} {' '.join(numbers)}".strip()
    return ingredient

def detect_allergen(ingredients):
    detected = set()
    for ing in ingredients:
        words = re.findall(r'\b\w+\b', ing.lower())
        for allergen, keywords in allergen_dict.items():
            for keyword in keywords:
                if keyword.lower() in words or (' ' in keyword and keyword.lower() in ing.lower()):
                    detected.add(allergen)
    return list(detected)

def detect_halal_status(ingredients):
    non_halal_found = []
    critical_found = []
    for ing in ingredients:
        words = ing.lower().split()
        if any(haram in words for haram in NON_HALAL):
            non_halal_found.append(ing)
        if any(crit in words for crit in CRITICAL_HALAL):
            critical_found.append(ing)
    
    if non_halal_found:
        return "NON-HALAL / HARAM", non_halal_found, critical_found
    elif critical_found:
        return "BUTUH PENGECEKAN", non_halal_found, critical_found
    return "HALAL", [], []

# --- 6. UI STREAMLIT ---
st.markdown("<style>.stMetric { background-color: #f0f2f6; padding: 15px; border-radius: 10px; }</style>", unsafe_allow_html=True)
st.title("🔍 Halal & Allergen Scanner")

tab_camera, tab_upload = st.tabs(["📸 Ambil Foto", "📁 Upload Gambar"])
source_img = None

with tab_camera:
    source_img = st.camera_input("Ambil foto komposisi")
with tab_upload:
    up_img = st.file_uploader("Pilih gambar", type=["jpg", "jpeg", "png"])
    if up_img: source_img = up_img

if source_img:
    file_bytes = np.asarray(bytearray(source_img.read()), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, 1)
    
    with st.status("Sedang menganalisis...", expanded=True) as status:
        st.write("Preprocessing gambar...")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        denoise = cv2.fastNlMeansDenoising(gray, h=10)
        thresh = cv2.threshold(denoise, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        st.write("Menjalankan OCR...")
        text_raw = pytesseract.image_to_string(thresh, lang='ind+eng')
        
        st.write("Pembersihan teks & Normalisasi...")
        clean = clean_text(text_raw)
        ings = extract_ingredients(clean)
        normalized = [normalize_ingredient(i) for i in ings]
        
        st.write("Cek Status Halal & Alergen...")
        allergens = detect_allergen(normalized)
        halal_status, non_halal_list, critical_list = detect_halal_status(normalized)
        
        status.update(label="Analisis Selesai!", state="complete")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if halal_status == "HALAL": st.success(f"### ✅ {halal_status}")
        elif "NON-HALAL" in halal_status: st.error(f"### ❌ {halal_status}")
        else: st.warning(f"### ⚠️ {halal_status}")
    with c2:
        st.metric("Bahan Terdeteksi", len(normalized))

    if non_halal_list: st.error(f"**Bahan Haram:** {', '.join(non_halal_list)}")
    if critical_list: st.info(f"**Titik Kritis:** {', '.join(critical_list)}")

    st.markdown("### 🥛 Alergen")
    if allergens:
        for a in allergens: st.warning(f"⚠️ **{a}**")
    else:
        st.write("✅ Aman dari alergen umum.")

    with st.expander("Lihat Detail Hasil"):
        st.write("**Teks Mentah OCR:**", text_raw)
        st.write("**Daftar Bahan (Sudah Koreksi):**", normalized)
        st.image(thresh, caption="Gambar yang diproses mesin")