import numpy as np
import matplotlib.pyplot as plt
from itertools import combinations

def get_complex_positions(N):
    """Generates complex coordinates for N points evenly spaced on the unit circle."""
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
    return np.exp(1j * angles)

def is_balanced(indices, N, tol=1e-5):
    """
    Checks if a given subset of beat indices is balanced (center of mass = 0).
    """
    positions = get_complex_positions(N)
    beat_positions = positions[list(indices)]
    vector_sum = np.sum(beat_positions)
    return np.abs(vector_sum) < tol

def find_balanced_rhythms(N, k):
    """Finds all balanced rhythms of length N with k beats."""
    positions = get_complex_positions(N)
    balanced_patterns = []
    
    for comb in combinations(range(N), k):
        if is_balanced(comb, N):
            balanced_patterns.append(comb)
            
    return balanced_patterns

def plot_cyclotomic_polygon(pattern, N, title="Balanced Rhythm"):
    """Plots the rhythm as a polygon inscribed in a circle."""
    angles = np.linspace(0, 2 * np.pi, 100)
    plt.figure(figsize=(6, 6))
    
    # Draw unit circle
    plt.plot(np.cos(angles), np.sin(angles), color='lightgray', linestyle='--')
    
    # Unit circle point locations
    positions = get_complex_positions(N)
    plt.scatter(positions.real, positions.imag, color='gray', s=30, zorder=2)
    
    # Highlight beat vertices
    beat_pos = positions[list(pattern)]
    plt.scatter(beat_pos.real, beat_pos.imag, color='crimson', s=100, zorder=4, label='Beats')
    
    # Connect beats to form the polygon (close loop)
    closed_pattern = list(pattern) + [pattern[0]]
    poly_pos = positions[closed_pattern]
    plt.plot(poly_pos.real, poly_pos.imag, color='crimson', linewidth=2, zorder=3)
    
    # Plot Center of Mass (should be at 0,0)
    center = np.mean(beat_pos)
    plt.scatter([center.real], [center.imag], color='blue', marker='x', s=100, zorder=5, label='Center of Mass (0,0)')
    
    plt.gca().set_aspect('equal', adjustable='box')
    plt.title(f"{title} (N={N}, k={len(pattern)})")
    plt.legend(loc='upper right')
    plt.grid(True, alpha=0.3)
    plt.show()

# --- Example Usage ---
N = 12  # 12-beat timeline (e.g., 12/8 or 4/4 measure in semiquavers)
k = 6   # 6 beats

balanced_rhythms = find_balanced_rhythms(N, k)
print(f"Found {len(balanced_rhythms)} balanced rhythms for N={N}, k={k}.")

# Plot the first balanced pattern found
if balanced_rhythms:
    print(f"Indices of first balanced pattern: {balanced_rhythms[0]}")
    plot_cyclotomic_polygon(balanced_rhythms[0], N, title="Cyclotomic Polygon")

