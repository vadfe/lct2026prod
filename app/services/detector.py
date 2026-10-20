from pathlib import Path

from PIL import Image
from ultralytics import YOLO


class DetectorService:
    def __init__(self, model_path: Path, confidence: float):
        if not model_path.is_file():
            raise FileNotFoundError(f"YOLO model not found: {model_path}")
        self.model = YOLO(str(model_path))
        self.confidence = confidence

    def best_box(self, image: Image.Image) -> tuple[float, float, float, float] | None:
        results = self.model.predict(source=image, conf=self.confidence, verbose=False)
        detections = []
        for result in results:
            for box in result.boxes:  # type: ignore
                coordinates = box.xyxy[0].tolist()
                detections.append((*coordinates, float(box.conf[0])))
        if not detections:
            return None
        best = max(detections, key=lambda item: item[4])
        return best[0], best[1], best[2], best[3]

    def find_all_labels(self, image: Image.Image) -> list[tuple[float, float, float, float]]:
        results = self.model.predict(source=image, conf=self.confidence, verbose=False)
        detections = []
        for result in results:
            for box in result.boxes:  # type: ignore
                coordinates = box.xyxy[0].tolist()
                detections.append((*coordinates, float(box.conf[0])))
        if not detections:
            return []
            
        # 1. Find main label (best confidence)
        best = max(detections, key=lambda item: item[4])
        main_box = (best[0], best[1], best[2], best[3])
        labels = [main_box]
        
        main_cx = (main_box[0] + main_box[2]) / 2
        main_area = (main_box[2] - main_box[0]) * (main_box[3] - main_box[1])
        main_w = main_box[2] - main_box[0]
        
        # 2. Find secondary labels
        for d in detections:
            box = (d[0], d[1], d[2], d[3])
            if box == main_box:
                continue
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area >= main_area:
                continue # Only smaller labels
                
            cx = (box[0] + box[2]) / 2
            
            # Check if it's vertically aligned (above or below, not on the side)
            if abs(cx - main_cx) < main_w * 0.7:
                labels.append(box)
                
        return labels
