import cv2
import sys
from paddleocr import PaddleOCR

def test_ocr(img_path):
    print(f"Testing {img_path}")
    ocr = PaddleOCR(use_angle_cls=True, lang='id', use_gpu=False, show_log=False)
    results = ocr.ocr(img_path)
    
    if not results or not results[0]:
        print("No text found")
        return
        
    for line in results[0]:
        print(line[1])

if __name__ == "__main__":
    test_ocr(sys.argv[1])
