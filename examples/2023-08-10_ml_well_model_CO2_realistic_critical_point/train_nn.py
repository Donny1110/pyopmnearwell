"""Train a neural network that predicts the well index from the permeability, initital
reservoir pressure and distance from the well."""

import csv
import logging
import os

import matplotlib.pyplot as plt
import tensorflow as tf
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.layers import Dense, Input
from tensorflow.keras.models import Sequential

from pyopmnearwell.ml.kerasify import export_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

dirpath: str = os.path.dirname(os.path.realpath(__file__))
savepath: str = os.path.join(dirpath, "model_pressure_radius_WI")
os.makedirs(savepath, exist_ok=True)
logdir: str = os.path.join(savepath, "logs")

# Load the entire dataset into a tensor for faster training.
logger.info("Load dataset.")
orig_ds = tf.data.Dataset.load(
    os.path.join(dirpath, "ensemble_runs", "pressure_radius_WI")
)
logger.info(
    f"Dataset at {os.path.join(dirpath, 'ensemble_runs', 'pressure_radius_WI')}"
    + f" contains {len(orig_ds)} samples."
)
# Adapt the input & output scaling.
features, targets = next(
    iter(orig_ds.batch(batch_size=len(orig_ds)).as_numpy_iterator())
)
logger.info("Adapt MinMaxScalers")
feature_scaler = MinMaxScaler()
target_scaler = MinMaxScaler()
feature_scaler.fit(features)
target_scaler.fit(targets)

# Write scaling to file
with open(os.path.join(savepath, "scales.csv"), "w", newline="") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=["variable", "min", "max"])
    writer.writeheader()
    data_min = feature_scaler.data_min_
    data_max = feature_scaler.data_max_
    for feature_name, feature_min, feature_max in zip(
        ["init_pressure", "radius"], data_min, data_max
    ):
        writer.writerow(
            {"variable": feature_name, "min": feature_min, "max": feature_max}
        )
    data_min = target_scaler.data_min_
    data_max = target_scaler.data_max_
    for feature_name, feature_min, feature_max in zip(["WI"], data_min, data_max):
        writer.writerow(
            {"variable": feature_name, "min": feature_min, "max": feature_max}
        )


# Shuffle once before splitting into training and val.
ds = orig_ds.shuffle(buffer_size=len(orig_ds))

# Split the dataset into a training and a validation data set.
train_size = int(0.9 * len(ds))
val_size = int(0.1 * len(ds))
train_ds = ds.take(train_size)
val_ds = ds.skip(train_size)

train_features, train_targets = next(
    iter(train_ds.batch(batch_size=len(train_ds)).as_numpy_iterator())
)
val_features, val_targets = next(
    iter(val_ds.batch(batch_size=len(val_ds)).as_numpy_iterator())
)
# Scale the features and targets.
train_features = feature_scaler.transform(train_features)
train_targets = target_scaler.transform(train_targets)
val_features = feature_scaler.transform(val_features)
val_targets = target_scaler.transform(val_targets)

logger.info(f"Scaled and transformed into training and validation dataset.")
# # Check the shape of the input and target tensors.
for x, y in train_ds:
    logger.info(f"shape of input tensor {x.shape}")
    logger.info(f"shape of output tensor {y.shape}")
    break


#  Create the neural network.
model = Sequential(
    [
        Input(shape=(2,)),
        Dense(10, activation="sigmoid", kernel_initializer="glorot_normal"),
        Dense(10, activation="sigmoid", kernel_initializer="glorot_normal"),
        Dense(10, activation="sigmoid", kernel_initializer="glorot_normal"),
        Dense(10, activation="sigmoid", kernel_initializer="glorot_normal"),
        Dense(10, activation="sigmoid", kernel_initializer="glorot_normal"),
        Dense(1),
    ]
)


# Callbacks for model saving, learning rate decay and logging.
checkpoint_callback = tf.keras.callbacks.ModelCheckpoint(
    os.path.join(savepath, "bestmodel"),
    monitor="val_loss",
    verbose=1,
    save_best_only=True,
    save_weights_only=True,
)
lr_callback = (
    tf.keras.callbacks.ReduceLROnPlateau(
        monitor="loss", factor=0.1, patience=10, verbose=1, min_delta=1e-10
    ),
)
tensorboard_callback = tf.keras.callbacks.TensorBoard(log_dir=logdir)


# Train the model.
model.compile(
    loss="mse",
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.1),
)
model.fit(
    train_features,
    train_targets,
    batch_size=600,
    epochs=100,
    # Ignore Pylance complaining. This is an typing error in tensorflow/keras.
    verbose=1,  # type: ignore
    validation_data=(val_features, val_targets),
    callbacks=[checkpoint_callback, lr_callback, tensorboard_callback],
)
model.save_weights(os.path.join(savepath, "finalmodel"))

# Load the best model and save to OPM format.
model.load_weights(os.path.join(savepath, "bestmodel"))
export_model(model, os.path.join(savepath, "WI.model"))

# Plot the trained model vs. the data.
# Sample from the unshuffled data set to have the elements sorted.
features, targets = next(
    iter(orig_ds.batch(batch_size=len(orig_ds)).as_numpy_iterator())
)

features = features.reshape((600, 395, 2))[::100, ...]
targets = targets.reshape((600, 395, 1))[::100, ...]
plt.figure
for feature, target in zip(features, targets):
    target_hat = target_scaler.inverse_transform(
        model(feature_scaler.transform(feature.reshape((395, 2))))
    )
    p = feature[0][0]
    plt.plot(
        feature[..., 1].flatten(),
        tf.reshape(target_hat, (-1)),
        label=rf"$p_i={p}$ [bar] nn",
    )
    plt.scatter(
        feature[..., 1].flatten()[::5],
        target.flatten()[::5],
        label=rf"$p_i={p}$ [bar] data",
    )
plt.legend()
plt.xlabel(r"$r[m]$")
plt.ylabel(r"$WI$ [m*s]")
plt.savefig(os.path.join(savepath, "nn_p_r_to_WI.png"))
plt.show()
