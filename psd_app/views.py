import os
import shutil
import logging  
from django.http import FileResponse, HttpResponseBadRequest
from django.shortcuts import render
from .forms import PSDUploadForm
from .utils import extract_layers_and_text
from django.conf import settings
from django.core.files.storage import FileSystemStorage

logger = logging.getLogger(__name__) 

def upload_psd(request):
    logger.info("\n---------------------------------------------------------------------------------------------------------------------------------------------")
    logger.info("Received PSD upload request")
    form = PSDUploadForm(request.POST, request.FILES)
    if request.method == 'POST':
        logger.debug("Processing POST request")
        if form.is_valid():
            psd_file = request.FILES['psd_file']
            logger.info(f"Processing PSD file: {psd_file.name}")

            if not psd_file.name.lower().endswith('.psd'):
                logger.warning(f"Invalid file type uploaded: {psd_file.name}")
                return HttpResponseBadRequest("Invalid file type. Only PSD files are allowed.")
            
            try:
                fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'temp_uploads'))
                filename = fs.save(psd_file.name, psd_file)
                temp_filepath = fs.path(filename)
                logger.debug(f"File saved temporarily at: {temp_filepath}")

                base_name = os.path.splitext(filename)[0]
                output_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads', base_name)
                os.makedirs(output_dir, exist_ok=True)
                logger.debug(f"Created output directory: {output_dir}")
                
                logger.info("Starting PSD processing")
                zip_path = extract_layers_and_text(temp_filepath, output_dir)
                logger.info("PSD processing completed")
                
                fs.delete(filename)
                logger.debug(f"Temporary file deleted: {filename}")
                
                if zip_path and os.path.exists(zip_path):
                    logger.info(f"Preparing zip file for download: {zip_path}")
                    response = FileResponse(
                        open(zip_path, 'rb'),
                        as_attachment=True,
                        filename='ftml-www.zip'
                    )
                    
                    try:
                        if os.path.exists(output_dir):
                            shutil.rmtree(output_dir)
                            logger.debug(f"Cleaned up output directory: {output_dir}")
                            
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                            logger.debug(f"Cleaned up zip file: {zip_path}")
                    except Exception as e:
                        logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
                    
                    logger.info("Successfully prepared file for download")
                    return response
                else:
                    logger.error("Zip file not found after processing")
                    return HttpResponseBadRequest("Error processing PSD file")
                    
            except Exception as e:
                logger.error(f"Error processing PSD file: {str(e)}", exc_info=True)
                return HttpResponseBadRequest("Error processing PSD file")
        else:
            logger.warning(f"Invalid form submission: {form.errors}")
    
    logger.debug("Rendering upload form")
    return render(request, 'psd_app/upload.html', {'form': form})
