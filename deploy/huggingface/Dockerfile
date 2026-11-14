# Hugging Face Space (Docker SDK) for the brain-MRI segmentation demo.
#
# This file and README.md go into the Space, next to the model files
# best_model.pt and experiment_config.json. The app code is not copied into the
# Space: the image clones it from GitHub when it is built. To deploy newer code,
# use "Factory rebuild" in the Space settings.
#
# See deploy/huggingface/HOSTING.md in the GitHub repository.

FROM python:3.9-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Spaces run the container as user id 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

ARG APP_REPO=https://github.com/salemaker47/senior_project_web.git
ARG APP_REF=main
RUN git clone --depth 1 --branch ${APP_REF} ${APP_REPO} .

# The exact package versions the project was tested with; CPU-only PyTorch.
RUN pip install --user torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --user -r requirements.lock.txt

# The Space's own files: this Dockerfile, README.md and the model files.
COPY --chown=user:user . /home/user/space/
RUN python deploy/huggingface/install_model.py /home/user/space model_store

ENV DJANGO_DEBUG=False \
    DJANGO_BEHIND_PROXY=True \
    DJANGO_SECURE_COOKIES=True \
    DJANGO_ALLOWED_HOSTS=* \
    DJANGO_CSRF_TRUSTED_ORIGINS=https://*.hf.space \
    DJANGO_FRAME_ANCESTORS=https://huggingface.co \
    PURGE_DAYS=1 \
    PORT=7860
EXPOSE 7860

CMD ["bash", "deploy/huggingface/start.sh"]
