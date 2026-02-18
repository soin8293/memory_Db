#!/usr/bin/env python3
"""int8 quantization for embedding storage optimization.

Reduces storage by ~4x by storing embeddings as int8 instead of float32.
Quality loss is minimal for cosine similarity search.

Usage:
    from memory_system.embeddings.quantize import quantize_int8, dequantize_int8

    # Quantize before storage
    blob = quantize_int8(embedding_vector)

    # Dequantize for search
    vector = dequantize_int8(blob)
"""

from __future__ import annotations

import struct
from typing import List, Tuple


def quantize_int8(vec: List[float]) -> bytes:
    """Quantize float32 embedding to int8 bytes.

    Process:
    1. Find max absolute value for scaling
    2. Scale to [-127, 127] range
    3. Round to nearest int8
    4. Store scale factor + int8 bytes

    Format: 4-byte float32 scale + N int8 values

    Args:
        vec: List of floats (embedding vector)

    Returns:
        bytes: Quantized representation (4 + len(vec) bytes)
    """
    if not vec:
        return b""

    # Find scale factor
    max_abs = max(abs(v) for v in vec)
    if max_abs < 1e-8:
        max_abs = 1.0  # Avoid division by zero

    scale = 127.0 / max_abs

    # Quantize to int8
    quantized = []
    for v in vec:
        q = int(round(v * scale))
        q = max(-127, min(127, q))  # Clamp to [-127, 127]
        quantized.append(q)

    # Pack: scale (float32) + quantized values (int8s)
    # Use 'b' format for signed int8
    return struct.pack("f", 1.0 / scale) + bytes((q + 128) for q in quantized)


def dequantize_int8(blob: bytes) -> List[float]:
    """Dequantize int8 bytes back to float32.

    Args:
        blob: Quantized bytes from quantize_int8()

    Returns:
        List of floats (reconstructed embedding)
    """
    if len(blob) < 4:
        return []

    # Unpack scale factor
    scale = struct.unpack("f", blob[:4])[0]

    # Unpack int8 values and scale
    values = []
    for b in blob[4:]:
        q = b - 128  # Convert back to signed
        values.append(q * scale)

    return values


def quantize_batch(vectors: List[List[float]]) -> List[bytes]:
    """Quantize multiple vectors."""
    return [quantize_int8(v) for v in vectors]


def dequantize_batch(blobs: List[bytes]) -> List[List[float]]:
    """Dequantize multiple vectors."""
    return [dequantize_int8(b) for b in blobs]


def measure_quantization_error(original: List[float], quantized_blob: bytes) -> float:
    """Measure mean squared error from quantization.

    Returns MSE between original and reconstructed vector.
    """
    reconstructed = dequantize_int8(quantized_blob)
    if len(original) != len(reconstructed):
        return float("inf")

    mse = sum((a - b) ** 2 for a, b in zip(original, reconstructed)) / len(original)
    return mse


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
    return dot / (norm_a * norm_b)


def measure_cosine_error(
    query: List[float],
    target: List[float],
    target_quantized: bytes,
) -> Tuple[float, float]:
    """Measure cosine similarity difference after quantization.

    Returns (original_cosine, quantized_cosine).
    """
    target_reconstructed = dequantize_int8(target_quantized)
    original_cos = cosine_similarity(query, target)
    quantized_cos = cosine_similarity(query, target_reconstructed)
    return original_cos, quantized_cos


# Storage comparison
def storage_ratio(dim: int) -> float:
    """Calculate storage ratio (quantized / original).

    Original: dim * 4 bytes (float32)
    Quantized: 4 + dim bytes (scale + int8s)
    """
    original_size = dim * 4
    quantized_size = 4 + dim
    return quantized_size / original_size


if __name__ == "__main__":
    # Self-test
    import random

    print("int8 quantization self-test")
    print("-" * 40)

    # Test with random vector
    dim = 384
    original = [random.gauss(0, 1) for _ in range(dim)]

    blob = quantize_int8(original)
    reconstructed = dequantize_int8(blob)

    mse = measure_quantization_error(original, blob)
    cos_orig, cos_quant = measure_cosine_error(original, original, blob)

    print(f"Dimension: {dim}")
    print(f"Original size: {dim * 4} bytes")
    print(f"Quantized size: {len(blob)} bytes")
    print(f"Storage ratio: {storage_ratio(dim):.2%}")
    print(f"MSE: {mse:.6f}")
    print(f"Self-cosine (original): {cos_orig:.6f}")
    print(f"Self-cosine (quantized): {cos_quant:.6f}")
    print(f"Cosine loss: {abs(cos_orig - cos_quant):.6f}")
