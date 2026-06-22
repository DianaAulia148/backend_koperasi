import os
from ultralytics import YOLO

def main():
    # Load YOLOv8 nano model (pre-trained, lightweight, good for mobile/realtime if exported to tflite later)
    print("Mempersiapkan model YOLOv8n untuk training...")
    model = YOLO('yolov8n.pt') 

    # Path to your dataset configuration
    data_yaml = r'D:\SEMESTER 6\data.yaml'

    print(f"Memulai training menggunakan dataset: {data_yaml}")
    print("Proses ini akan memakan waktu tergantung spesifikasi CPU/GPU.")
    
    # Train the model
    results = model.train(
        data=data_yaml,
        epochs=50,       # Anda bisa ubah jumlah epochs (50 cukup untuk tes awal)
        imgsz=640,       # Ukuran gambar yang optimal untuk YOLOv8
        batch=16,        # Batch size
        name='ktp_model' # Hasil akan disimpan di folder runs/detect/ktp_model
    )

    print("\nTraining Selesai!")
    print("Model terbaik telah disimpan di: runs/detect/ktp_model/weights/best.pt")

if __name__ == '__main__':
    main()
