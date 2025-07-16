ARG LITELLM_NAMESPACE
ARG LITELLM_VERSION

FROM $LITELLM_NAMESPACE:$LITELLM_VERSION

EXPOSE 8080
WORKDIR /app
COPY ./app/ /app/

RUN python3 -m pip install -r requirements.txt --no-cache-dir

CMD ["python3", "./main.py"]

ENTRYPOINT [""]
