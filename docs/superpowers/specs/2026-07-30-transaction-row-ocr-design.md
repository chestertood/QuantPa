# Transaction Row Detection + pytesseract OCR — Design

## Purpose
`backend/Finance_history.py` currently OCRs a whole deposit-history screenshot with
easyocr and reconstructs transaction rows via a fragile line-by-line state machine
(`parse_transactions`), plus a hardcoded left/right image crop. This breaks when OCR
line order is noisy or a row is cut off at the screen edge.

Goal: detect each transaction row's bounding box first, then OCR within each row,
so parsing no longer depends on guessing line order across the whole image.

## Architecture

```
process_image(path)
  -> load image, convert to grayscale
  -> detect_row_bands(gray)         # step 1: row bounding boxes
  -> for each band:
       ocr_row(image, band)         # step 2+3: tight text boxes + field grouping
       -> classify()                # unchanged
  -> list[dict] records
```

### 1. Row detection — `detect_row_bands(gray: np.ndarray) -> list[tuple[int, int]]`
Each transaction row is a fixed-height block separated by near-blank horizontal gaps
(faint divider lines / whitespace between rows). Compute a horizontal projection
profile: row-wise sum of non-background pixel intensity. Runs of near-zero rows are
gaps; the bands between gaps (above a minimum height threshold, to drop noise) are
returned as `(y_start, y_end)` pixel ranges spanning the full image width. A partial
row cut off at the top/bottom of the screenshot (from scrolling) that's too short is
dropped.

No ML model, no training data — relies on the fixed, evenly-spaced app layout.

### 2. Per-row OCR — `ocr_row(image: np.ndarray, band: tuple[int, int]) -> dict`
Crop the image to the row band (full width, small vertical padding), upscale ×3, and
run `pytesseract.image_to_data(img, lang="tha+eng", output_type=Output.DICT)`. This
returns tight per-line bounding boxes (`left`, `top`, `width`, `height`, `text`)
grouped by `block_num`/`par_num`/`line_num` — no more hardcoded left/right crop.

Group detected lines by x-position: lines whose box center falls in the left half of
the row become the "label" cluster (icon + bank name, then datetime below); lines in
the right half become the "amount" cluster (amount, then status below). Within each
cluster, sort by `top` to get line order.

- Label cluster: line 1 = label text (bank name, or "ฝากเงิน" for deposits), line 2 =
  matched against `DATETIME_RE` (existing regex) to extract the datetime.
- Amount cluster: line 1 matched against `AMOUNT_RE` (existing regex) for the amount,
  line 2 = status text ("ทำรายการสำเร็จ"/ไม่สำเร็จ).

Returns `{"label": str, "amount": float, "datetime": str, "status": str}` — same
shape `parse_transactions` used to build per-row, but produced directly instead of
via cross-row state tracking.

### 3. Classification
`_classify()` is unchanged — still takes a row dict and returns the final record
(deposit if `label == "ฝากเงิน"`, else treats label as the withdrawal's destination
bank).

### What gets removed
- `parse_transactions()` (line-by-line state machine) — replaced by
  `detect_row_bands` + `ocr_row`, which no longer need cross-row guessing.
- `upscale()`'s `half="left"/"right"` fixed-crop parameter — replaced by
  `image_to_data`'s actual per-line boxes.
- easyocr dependency — replaced by pytesseract (`lang="tha+eng"`).

### What stays
- `AMOUNT_RE`, `DATETIME_RE`, `DEPOSIT_LABEL`, `WITHDRAW_LABEL`, `_classify()`.
- Upscaling before OCR (still helps tesseract accuracy on small text).

## Error handling
If a row's label/amount cluster is missing a regex match (OCR noise, unexpected
layout), skip that row with a printed warning rather than crashing the whole batch —
matches current script's tolerance for partial failures across multiple screenshots.

## Testing
Run the script against the 5 existing sample screenshots in `backend/deposit_history/`.
For each, manually cross-check the printed row count and a few amounts/dates against
the screenshot. No automated test suite requested — this is a manual verification
script, consistent with the current `__main__` block.

## Out of scope
- Building/installing the `tesseract.exe` binary (currently only Tesseract source is
  present in `tesseract-main/`) — separate environment setup, not part of this design.
- Handling screenshots from apps other than SCB's — layout assumption is specific to
  the current sample set.
