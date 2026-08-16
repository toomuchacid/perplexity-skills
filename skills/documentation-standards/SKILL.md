---
name: documentation-standards
description: Documentation conventions for coding projects. Enforces inline docstring standards (module, class, method-level Google style), inline comment rules, and standalone docs/ folder structure. Documentation is written alongside code in every phase, not as a separate step. Use when writing, reviewing, or documenting code.
---

# Documentation Standards

This file defines the documentation conventions for coding projects. Every phase must follow these standards. Code and docs are written together, not as separate steps.

## Inline Code Documentation

### Module-Level Docstring (every .py file)

```python
"""
<Subsystem Name> — <Module Name> (Phase N)

<One paragraph describing what this module does and its role in the architecture.>

Key classes:
    ClassName: One-line summary

Dependencies:
    - package_name (purpose)

Hardware:
    - Runs on <GPU/CPU assignment> if applicable

See also:
    - docs/phaseN-<module>.md for usage guide
    - config/settings.yaml for configuration
"""
```

### Class Docstrings

```python
class CardDetector:
    """Detects card-shaped objects in camera frames.

    Uses YOLO object detection as the primary method with an OpenCV
    contour-based fallback for environments without a fine-tuned model.
    Designed to run on the primary vision GPU (cuda:0).

    Args:
        config: Detection configuration from settings.yaml.
        device: PyTorch device string (default from config).

    Example:
        >>> detector = CardDetector(config.detection)
        >>> detections = detector.detect(frame)
        >>> for det in detections:
        ...     print(f"Card at {det.bbox} conf={det.confidence:.2f}")
    """
```

### Method Docstrings (Google style)

```python
def detect(self, frame: np.ndarray) -> list[Detection]:
    """Detect card objects in a single frame.

    Args:
        frame: BGR image as numpy array, any resolution.

    Returns:
        List of Detection objects with bounding boxes, confidence
        scores, and orientation (tapped/untapped). Empty list if
        no cards found.

    Raises:
        RuntimeError: If the YOLO model fails to load.
    """
```

### Inline Comments

- Explain WHY, not what: `# WRatio handles partial OCR reads better than ratio`
- Mark phase boundaries: `# --- Phase 1: Single Camera ---`
- Mark future integration points: `# TODO(Phase 2): Replace with ByteTrack`
- Document threshold reasoning: `# 0.716 = standard MTG card ratio (63mm / 88mm)`

## Standalone Documentation (docs/ folder)

Each phase produces these markdown files:

### Required per phase

- `docs/phaseN-overview.md` — Scope, goals, architecture changes, limitations
- `docs/phaseN-<module>.md` — One per major module built in that phase

### Each module doc must include

- **Purpose** — What it does and its role in the architecture
- **How it works** — Technical description of the approach
- **Configuration** — All relevant settings.yaml keys with types and defaults
- **Usage** — Code examples for common tasks
- **Troubleshooting** — Common errors and fixes

### Project-wide docs (updated as needed)

- `docs/README.md` — Index of all documentation
- `docs/development-guide.md` — Dev setup, conventions, testing, phase roadmap
- `docs/configuration-reference.md` — Complete settings.yaml reference

## Commit Convention

Documentation is committed alongside the code it describes, not in a separate PR.
