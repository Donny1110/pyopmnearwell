# SPDX-FileCopyrightText: 2023 NORCE
# SPDX-FileCopyrightText: 2023 UiB
# SPDX-License-Identifier: GPL-3.0

""""
Script to run Flow for a random input variable
"""

import os
import math
import numpy as np
from ecl.eclfile import EclFile
from mako.template import Template
import matplotlib
import matplotlib.pyplot as plt

np.random.seed(7)


def compute_peaceman(k_h: float, r_e: float, r_w: float) -> float:
    r"""Compute the well productivity index (adjusted for density and viscosity)
    from the Peaceman well model.
    .. math::
        WI\cdot\frac{\mu}{\rho} = \frac{2\pi hk}{\ln (r_e/r_w)}
    Parameters:
        k_h: Permeability times the cell thickness (thickness fix to 1 m).
        r_e: Equivalent well-block radius.
        r_w: Wellbore radius.
    Returns:
        :math:`WI\cdot\frac{\mu}{\rho}`
    """
    w_i = (2 * math.pi * k_h) / (math.log(r_e / r_w))
    return w_i


# Give the full path to PYOPMNEARWELL and model parameters (ranges and inj rate based on the csp11b model)
PYOPM = "/Users/dmar/Github/pyopmnearwell"
FLOW = f"{PYOPM}/build/opm-simulators/bin/flow_gaswater_dissolution_diffuse"
PERMEABILITY = 1e-12 # K between 1e-13 to 1e-12 m2
WELLRADI = 0.1 # Between 0.025 to 0.125 m
RATE = 1.668e-05 # [sm3/s] Fix to 1.665e-2 kg/s, ref_dens = 998.108 kg/sm3
BOFAC = 1.0
VISCOSCITY = 0.6532 * 0.001
CLIP = 2 # Remove the distances with value less than this [m]

#Run the main routine
NPOINTS, NPRUNS = 20, 5
PERMEABILITYHS = np.linspace(1e-13, 1e-11, NPOINTS)  # K between 1e-13 to 1e-12 m2 and H betweem 1 to 10, i,e, [1e-13,1e-11]
#WELLRADIS = [0.025, .05, .1, .125]
#WELLRADIS = np.linspace(.05, .125, NPOINTS)
WELLRADIS = [0.1, .125]
nradis = len(WELLRADIS)
nperm = len(PERMEABILITYHS)
wi_simulated = []
wi_analytical = []
r_e = []
r_w = []
r_wi = []
mytemplate = Template(filename="h2o_nearwell.mako")
for k, WELLRADI in enumerate(WELLRADIS):
    r_w.append(WELLRADI)
    for i, PERMEABILITYH in enumerate(PERMEABILITYHS):
        var = {"flow": FLOW, "perm": PERMEABILITYH, "radius": WELLRADI, "rate": RATE, "pwd": os.getcwd()}
        filledtemplate = mytemplate.render(**var)
        with open(
            f"h2o_{i+k*nperm}.txt",
            "w",
            encoding="utf8",
        ) as file:
            file.write(filledtemplate)
        r_wi.append(WELLRADI)

fig, axis = plt.subplots()
axis.set_yscale("log")
for i in range(round(nradis * NPOINTS / NPRUNS)):
    os.system(
        f"pyopmnearwell -i h2o_{NPRUNS*i}.txt -o h2o_{NPRUNS*i} -p '' & "
        + f"pyopmnearwell -i h2o_{NPRUNS*i+1}.txt -o h2o_{NPRUNS*i+1} -p '' & "
        + f"pyopmnearwell -i h2o_{NPRUNS*i+2}.txt -o h2o_{NPRUNS*i+2} -p '' & "
        + f"pyopmnearwell -i h2o_{NPRUNS*i+3}.txt -o h2o_{NPRUNS*i+3} -p '' & "
        + f"pyopmnearwell -i h2o_{NPRUNS*i+4}.txt -o h2o_{NPRUNS*i+4} -p '' & wait"
    )
    for j in range(NPRUNS):
        POSITIONS = np.load(f"./h2o_{NPRUNS*i+j}/output/xspace.npy")
        cell_centers = 0.5 * (POSITIONS[2:] + POSITIONS[1:-1])
        cell_centers = cell_centers[CLIP <= cell_centers]
        r_e.append(cell_centers)
        wi_analytical.append([])
        for r in r_e[-1]:
            wi_analytical[-1].append(
                compute_peaceman(PERMEABILITYH, r,r_wi[NPRUNS*i+j]) * BOFAC / VISCOSCITY
            )
        rst = EclFile(f"./h2o_{NPRUNS*i+j}/output/RESERVOIR.UNRST")
        pressure = np.array(rst.iget_kw("PRESSURE")[-1])
        pw = pressure[0]
        cell_pressures = pressure[len(pressure)-len(r_e[-1]):]
        wi_simulated.append(RATE / ((pw - cell_pressures) * 1e5)) # 1e5 to connvert from bar to Pascals
        axis.plot(
            r_e[-1],
            wi_simulated[-1],
            color=matplotlib.colormaps["tab20"].colors[(NPRUNS*i+j)%20],
            linestyle="",
            marker="*",
            markersize=5,
            label="sim",
        )
        axis.plot(
            r_e[-1],
            wi_analytical[-1],
            color=matplotlib.colormaps["tab20"].colors[(NPRUNS*i+j)%20],
            linestyle="",
            marker=".",
            markersize=5,
            label="peaceman",
        )
        os.system(f"rm -rf h2o_{NPRUNS*i+j} h2o_{NPRUNS*i+j}.txt")

# Write the configuration files for the comparison in the 3D reservoir
var = {"flow": FLOW, "perm": PERMEABILITY, "radius": .1, "rate": RATE, "pwd": os.getcwd()}
for name in ["3d_flow_wellmodel", "3d_ml_wellmodel"]:
    mytemplate = Template(filename=f"h2o_{name}.mako")
    filledtemplate = mytemplate.render(**var)
    with open(
        f"h2o_{name}.txt",
        "w",
        encoding="utf8",
    ) as file:
        file.write(filledtemplate)

axis.set_ylabel(r"WI [sm${^3}$/(Pa s)]", fontsize=12)
axis.set_xlabel("Distance to well [m]", fontsize=12)
axis.legend(fontsize=4)
fig.savefig("analytical_and_simulated_wellindex.png")

# Save the required quantities for the ML routine
np.save("re", r_e[-1])
np.save("rw", r_w)
np.save("kh", PERMEABILITYHS)
np.save("wi", wi_simulated)

# Run the ML script
os.system("python3 ml_routine.py")

# Use our pyopmnearwell friend to run the 3D simulations and compare the results
os.system("rm -rf h2o_nearwell")
os.system("pyopmnearwell -i h2o_3d_flow_wellmodel.txt -o h2o_3d_flow_wellmodel")
os.system("pyopmnearwell -i h2o_3d_ml_wellmodel.txt -o h2o_3d_ml_wellmodel")
os.system("pyopmnearwell -c compare")
