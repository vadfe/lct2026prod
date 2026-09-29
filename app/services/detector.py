from pathlib import Path

from PIL import Image
from ultralytics import YOLO


class DetectorService:
    def __init__(self, model_path: Path, confidence: float):
        if not model_path.is_file():
            raise FileNotFoundError(f"YOLO model not found: {model_path}")
        self.model = YOLO(str(model_path))
        self.confidence = confidence

    def best_box(
        self,
        image: Image.Image,
        conf: float | None = None,
        prefer_center: bool = True,
    ) -> tuple[float, float, float, float] | None:
        threshold = self.confidence if conf is None else conf
        results = self.model.predict(source=image, conf=threshold, verbose=False)
        detections = []
        for result in results:
            for box in result.boxes:
                coordinates = box.xyxy[0].tolist()
                detections.append((*coordinates, float(box.conf[0])))
        if not detections:
            return None

        if prefer_center:
            # Prefer bounding boxes located in the central region of the image.
            # If several boxes fall into the center, pick the one with the
            # highest confidence. Otherwise fall back to the highest-confidence
            # box anywhere in the image.
            left = image.width * 0.25
            right = image.width * 0.75
            top = image.height * 0.25
            bottom = image.height * 0.75

            central = []
            for x1, y1, x2, y2, score in detections:
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                if left <= cx <= right and top <= cy <= bottom:
                    central.append((x1, y1, x2, y2, score))

            if central:
                best = max(central, key=lambda item: item[4])
                return best[0], best[1], best[2], best[3]

        best = max(detections, key=lambda item: item[4])
        return best[0], best[1], best[2], best[3]
