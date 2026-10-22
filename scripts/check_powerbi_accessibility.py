"""Render labelled/marked palette under Machado et al. 2009 CVD simulations.

Matrices: https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html
Color alone is insufficient; the report also uses names, markers, dashes and signed labels.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import colors
import matplotlib.pyplot as plt
import numpy as np


def main():
    root = Path("powerbi/JetFuelHedgeRisk/JetFuelHedgeRisk.Report")
    theme = json.loads((root/"StaticResources/RegisteredResources/jet_fuel_theme.json").read_text(encoding="utf-8"))
    palette = np.array([colors.to_rgb(c) for c in theme["dataColors"]])
    matrices = {"Normal": np.eye(3),
        "Protanopia": np.array([[.152286, 1.052583, -.204868], [.114503, .786281, .099216], [-.003882, -.048116, 1.051998]]),
        "Deuteranopia": np.array([[.367322, .860646, -.227968], [.280085, .672501, .047413], [-.011820, .042940, .968881]]),
        "Tritanopia": np.array([[1.255528, -.076749, -.178779], [-.078411, .930809, .147602], [.004733, .691367, .303900]])}
    linear = np.where(palette <= .04045, palette/12.92, ((palette+.055)/1.055)**2.4)
    names = ["Jet", "WTI", "Heating oil", "Brent", "Crack"]
    fig, axes = plt.subplots(4, 1, figsize=(12.8, 7.2), layout="constrained")
    fig.suptitle("Color-vision QA: retain names, markers and line styles in addition to hue", fontweight="bold")
    for ax, (condition, matrix) in zip(axes, matrices.items()):
        simulated = np.clip(linear @ matrix.T, 0, 1)
        simulated = np.where(simulated <= .0031308, 12.92*simulated, 1.055*simulated**(1/2.4)-.055)
        for i, (label, tint, marker, dash) in enumerate(zip(names, simulated, ["o", "s", "D", "^", "x"], ["-", "--", "-.", ":", "-"])):
            ax.plot([i-.3, i+.3], [0, 0], color=tint, lw=5, ls=dash, marker=marker, markersize=12)
            ax.text(i, -.3, label, ha="center", color="#111111")
        ax.set(ylim=(-.6, .4), xlim=(-.6, 4.6), title=condition)
        ax.axis("off")
    target = Path("dashboard/plots/insights/pbir_previews/palette_cvd.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=100)
    plt.close(fig)
    print("CVD palette preview generated; inspect labels/markers and actual report visuals")


if __name__ == "__main__":
    main()
