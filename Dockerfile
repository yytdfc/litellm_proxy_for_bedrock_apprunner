ARG LITELLM_VERSION

FROM litellm/litellm:$LITELLM_VERSION

EXPOSE 8080
WORKDIR /app
COPY ./app/ /app/

RUN python3 -m pip install -r requirements.txt --no-cache-dir

CMD ["python3", "./main.py"]

ENTRYPOINT [""]
