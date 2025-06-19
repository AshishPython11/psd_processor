import math
import os
import re
import json
import cv2
import pytesseract
import json
import numpy as np
import logging
from psd_tools import PSDImage
import zipfile

logger = logging.getLogger(__name__)

def sanitize_filename(name):
    logger.debug(f"Sanitizing filename: {name}")
    name = name.strip()
    name = re.sub(r'[\s\\/:*?"<>|]+', "_", name)
    sanitized = name if name else "unnamed_layer"
    logger.debug(f"Sanitized filename: {sanitized}")
    return sanitized

def create_zip_file(output_dir):
    """Creates a ZIP file containing all files and empty folders in the output directory"""
    logger.info(f"Creating zip file from directory: {output_dir}")
    zip_filename = f"ftml-www.zip"
    zip_path = os.path.join(os.path.dirname(output_dir), zip_filename)
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Walk through all directories and files
            for root, dirs, files in os.walk(output_dir):
                # Add empty directories first
                for dir_name in dirs:
                    abs_dir_path = os.path.join(root, dir_name)
                    rel_dir_path = os.path.relpath(abs_dir_path, output_dir)
                    logger.debug(f"Adding directory to zip: {rel_dir_path}")
                    # Create a ZipInfo object for the directory
                    zip_info = zipfile.ZipInfo(rel_dir_path + '/')
                    # Add directory to zip (empty directories need to end with /)
                    zipf.writestr(zip_info, '')
                
                # Add files
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, output_dir)
                    logger.debug(f"Adding file to zip: {arcname}")
                    zipf.write(file_path, arcname)
        
        logger.info(f"Successfully created zip file at: {zip_path}")
        return zip_path
    except Exception as e:
        logger.error(f"Error creating zip file: {str(e)}", exc_info=True)
        raise

def preprocess_image(image_path):
    logger.info(f"Preprocessing image: {image_path}")
    try:
        image = cv2.imread(image_path)
        if image is None:
            logger.error(f"Failed to read image at path: {image_path}")
            raise FileNotFoundError(f"Image not found at path: {image_path}")
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
        logger.debug("Image preprocessing completed successfully")
        return image, thresh
    except Exception as e:
        logger.error(f"Error preprocessing image: {str(e)}", exc_info=True)
        raise

def get_psd_dpi(psd):
    try:
        res_info = psd.image_resources.get_data("resolution_info")
        dpi = res_info.get("horizontal_resolution", 72.0)
        logger.debug(f"PSD DPI: {dpi}")
        return dpi
    except Exception as e:
        logger.warning(f"Could not get PSD DPI, using default 72.0: {str(e)}")
        return 72.0

def process_text_layer(layer, dpi):
    logger.debug(f"Processing text layer: {layer.name}")
    try:
        engine_dict = layer.engine_dict
        text = layer.text
        
        style_data = engine_dict.get('StyleRun', {}).get('RunArray', [{}])[0].get('StyleSheet', {}).get('StyleSheetData', {})
        paragraph_data = engine_dict.get('ParagraphRun', {}).get('RunArray', [{}])[0].get('ParagraphSheet', {}).get('Properties', {})

        scale_y = layer.transform[3] if layer.transform else 1.0
        font_size = float(style_data.get('FontSize', 12)) * scale_y
        estimated_font_size = 96/72 * font_size
        line_height = int(round(float(style_data.get('Leading', font_size * 1.2))))

        # Text color (RGBA to hex)
        fill_color = style_data.get('FillColor', {}).get('Values', [1.0, 0.0, 0.0, 1.0])
        color = f"0x{int(fill_color[1]*255):02x}{int(fill_color[2]*255):02x}{int(fill_color[3]*255):02x}"
        
        # Justification
        justification_map = {0: "left", 1: "right", 2: "center", 3: "justify"}
        justification = justification_map.get(paragraph_data.get('Justification', 0), "left")
        
        # Uppercase flag
        uppercase = style_data.get('FontCaps', 0) == 2  # 2 = AllCaps

        # Bounding box
        x1, y1, x2, y2 = layer.bbox
        width = x2 - x1
        height = y2 - y1

        layer_data = {
            "type": "text",
            "font": get_font_name(layer),
            "justification": justification,
            "lineHeight": line_height,
            "color": color,
            "size": math.ceil(estimated_font_size),
            "name": sanitize_filename(layer.name),
            "x": x1,
            "y": y1,
            "width": width,
            "height": height,
            "text": text
        }

        if uppercase:
            layer_data["uppercase"] = True

        logger.debug(f"Successfully processed text layer: {layer.name}")
        return layer_data
    except Exception as e:
        logger.error(f"Error processing text layer {layer.name}: {str(e)}", exc_info=True)
        raise

def get_font_name(layer):
    """Extract font name from resource_dict or engine_dict"""
    try:
        if hasattr(layer, 'resource_dict'):
            fonts = layer.resource_dict.get('FontSet', [])
            if fonts:
                font_name = str(fonts[0].get('Name', 'Unknown')).replace("'", "")
                logger.debug(f"Found font name: {font_name}")
                return font_name
        logger.debug("No font name found, returning empty string")
        return ""
    except Exception as e:
        logger.error(f"Error getting font name: {str(e)}", exc_info=True)
        return ""

def extract_text_regions(image, thresh):
    logger.info("Extracting text regions from image")
    try:
        data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
        text_boxes = []
        processed_indices = set()
        y_tolerance = 5

        for i in range(len(data["text"])):
            if i in processed_indices or not data["text"][i].strip():
                continue

            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            same_line_words = [data["text"][i]]
            total_width = w

            for j in range(i + 1, len(data["text"])):
                if not data["text"][j].strip():
                    continue
                if abs(data["top"][j] - y) <= y_tolerance:
                    same_line_words.append(data["text"][j])
                    total_width = data["left"][j] + data["width"][j] - x
                    processed_indices.add(j)

            combined_text = "_".join(same_line_words)
            text_boxes.append({
                'x': x,
                'y': y,
                'width': total_width,
                'height': h,
                'text': combined_text
            })
            logger.debug(f"Extracted text region: {combined_text}")

            processed_indices.add(i)

        logger.info(f"Successfully extracted {len(text_boxes)} text regions")
        return text_boxes
    except Exception as e:
        logger.error(f"Error extracting text regions: {str(e)}", exc_info=True)
        raise

def safe_json_dump(data, filepath):
    """Handles all serialization issues with comprehensive type checking"""
    logger.info(f"Saving JSON data to: {filepath}")
    def serialize(obj):
        if obj is None:
            return None
        elif isinstance(obj, (str, bytes)):
            # Clean string of any problematic characters
            return str(obj).encode('ascii', 'ignore').decode('ascii')
        elif isinstance(obj, (int, float, bool)):
            return obj
        elif isinstance(obj, (np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, (np.int32, np.int64)):
            return int(obj)
        elif isinstance(obj, (list, tuple)):
            return [serialize(item) for item in obj]
        elif isinstance(obj, dict):
            return {str(k): serialize(v) for k, v in obj.items()}
        else:
            return str(obj)  # Fallback to string representation
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(serialize(data), f, indent=2, ensure_ascii=False)
        logger.info("Successfully saved JSON data")
    except Exception as e:
        logger.error(f"Error saving JSON data: {str(e)}", exc_info=True)
        raise

def extract_layers_and_text(psd_path, output_dir):
    logger.info("\n---------------------------------------------------------------------------------------------------------------------------------------------")
    logger.info(f"Starting PSD processing: {psd_path}")
    try:
        psd = PSDImage.open(psd_path)
        logger.info("Successfully opened PSD file")
    except Exception as e:
        logger.error(f"Error opening or parsing PSD file: {str(e)}", exc_info=True)
        raise

    layers_json = []
    base_name = os.path.splitext(os.path.basename(psd_path))[0]

    ftml_root = os.path.join(output_dir, "ftml-www")
    fonts_dir = os.path.join(ftml_root, "fonts")
    json_dir = os.path.join(ftml_root, "json")
    logs_dir = os.path.join(ftml_root, "logs")
    skins_dir = os.path.join(ftml_root, "skins", base_name)

    os.makedirs(fonts_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(skins_dir, exist_ok=True)
    
    logger.debug("Creating output directories")
    for d in [fonts_dir, json_dir, logs_dir, skins_dir]:
        os.makedirs(d, exist_ok=True)
        logger.debug(f"Created directory: {d}")

    dpi = get_psd_dpi(psd)
    logger.info(f"Processing PSD with DPI: {dpi}")

    for layer in psd.descendants():
        if layer.is_group():
            continue
        if not layer.is_visible():
            continue

        try:
            # Handle text layers
            if hasattr(layer, 'text') and layer.text:
                logger.debug(f"Processing text layer: {layer.name}")
                text_layer_data = process_text_layer(layer, dpi)
                layers_json.append(text_layer_data)
                continue
            
            # Handle image layers
            logger.debug(f"Processing image layer: {layer.name}")
            layer_image = layer.topil()
            if layer_image is None or layer_image.width == 0 or layer_image.height == 0:
                logger.warning(f"Skipping empty image layer: {layer.name}")
                continue

            base_filename = sanitize_filename(layer.name)
            output_filename = f"{base_filename}.png"
            output_filepath = os.path.join(skins_dir, output_filename)

            counter = 1
            while os.path.exists(output_filepath):
                output_filename = f"{base_filename}_{counter}.png"
                output_filepath = os.path.join(skins_dir, output_filename)
                counter += 1

            layer_image.save(output_filepath, format="PNG")
            logger.debug(f"Saved image layer: {output_filename}")

            x1, y1, x2, y2 = layer.bbox
            layers_json.append({
                "type": "image",
                "src": f"../skins/{os.path.basename(skins_dir)}/{output_filename}",
                "name": os.path.splitext(output_filename)[0],
                "x": x1,
                "y": y1,
                "width": x2 - x1,
                "height": y2 - y1
            })

        except Exception as e:
            logger.error(f"Error processing layer '{layer.name}': {str(e)}", exc_info=True)

        # Run OCR on the full composite image
        full_image_path = os.path.join(skins_dir, output_filename)
        if os.path.exists(full_image_path):
            try:
                logger.info(f"Running OCR on image: {full_image_path}")
                image, thresh = preprocess_image(full_image_path)
                text_regions = extract_text_regions(image, thresh)
                
                # Get all existing text layer bounding boxes
                existing_text_boxes = [l for l in layers_json if l['type'] == 'text']

                for region in text_regions:
                    # Check if this region overlaps with any existing text layer
                    overlaps = False
                    for text_box in existing_text_boxes:
                        if (region['x'] < text_box['x'] + text_box['width'] and
                            region['x'] + region['width'] > text_box['x'] and
                            region['y'] < text_box['y'] + text_box['height'] and
                            region['y'] + region['height'] > text_box['y']):
                            overlaps = True
                            break
                    
                    if not overlaps:
                        logger.debug(f"Adding OCR text region: {region['text']}")
                        layers_json.append({
                            "type": "text",
                            "name": region['text'].replace(" ", "_"),
                            "x": region['x'],
                            "y": region['y'],
                            "width": region['width'],
                            "height": region['height'],
                            "text": region['text'].replace("_", " "),
                            "lineHeight": region['height'],
                            "size": int(region['height'] * 0.8),
                            "color": "0x000000"
                        })
            except Exception as e:
                logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
        else:
            logger.warning(f"OCR skipped: image not found at {skins_dir}")

    # Final JSON structure
    final_output = {
        "name": base_name,
        "path": f"{base_name}/",
        "info": {
            "description": "Normal",
            "file": os.path.basename(psd_path),
            "date": "sRGB",
            "title": "",
            "author": "",
            "keywords": "",
            "generator": "Font Detection v1.0"
        },
        "layers": layers_json
    }
    
    json_output_path = os.path.join(json_dir, "layers.json")
    try:
        logger.info("Saving layers JSON")
        safe_json_dump(final_output, json_output_path)
    except Exception as e:
        logger.error(f"Critical error saving JSON: {str(e)}", exc_info=True)
        # Try one more time with even more aggressive cleaning
        try:
            with open(json_output_path, 'w', encoding='utf-8') as f:
                json.dump(str(final_output), f, indent=2)
            logger.info("Saved JSON as string representation")
        except Exception as e:
            logger.exception(f"Failed completely to save JSON: {str(e)}")
            raise
    
    logger.info("Creating final zip file")
    zip_path = create_zip_file(output_dir)
    logger.info(f"PSD processing completed successfully. Output: {zip_path}")
    
    return zip_path  


