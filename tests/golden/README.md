# Golden files

Put real pairs here to check that the web app reproduces the training repo's
predictions. The folder is empty by default and the golden test is skipped.

```
tests/golden/<model_key>/<name>.png        256x256 preprocessed image
                                           (Drive: data/<dataset>/processed/images/<image_id>.png)
tests/golden/<model_key>/<name>_mask.png   the mask that model predicted for it
                                           (the NB05 prediction PNG of the same fold
                                           that model_store/<model_key>/ serves)
```

`<model_key>` must match a folder in `model_store/`. The pair folders are
git-ignored (real dataset images that only make sense together with the
git-ignored model), so a fresh clone has none and the test is skipped there. The test runs each image
with blob removal off and requires Dice >= 0.99 against the stored mask.
Use an image from the test split of the fold the registry picks (highest
`best_score`); `python -m inference list` prints that fold.
