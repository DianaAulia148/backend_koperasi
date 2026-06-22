import json
import os
os.environ['FLAGS_use_mkldnn'] = '0'
from paddleocr import PaddleOCR

def main():
    ocr = PaddleOCR(use_angle_cls=True, lang='id', enable_mkldnn=False)
    res = ocr.ocr('runs/detect/ktp_model/val_batch0_labels.jpg')
    
    # Dump type
    output = {
        'type_res': str(type(res)),
        'len_res': len(res) if hasattr(res, '__len__') else 0,
        'res_dump': []
    }
    
    if isinstance(res, list):
        for item in res:
            if hasattr(item, '__dict__'):
                output['res_dump'].append(str(item.__dict__))
            elif hasattr(item, 'keys'): # dict
                output['res_dump'].append({k: str(v) for k,v in item.items()})
            else:
                output['res_dump'].append(str(item))
                
    with open('scratch_res.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=4)

if __name__ == '__main__':
    main()
