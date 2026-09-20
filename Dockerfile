# Custom Minecraft server: vanilla / Fabric / Forge / NeoForge, version chosen at start via env.
# Several Java runtimes are baked in; mcctl picks the one the Minecraft version needs
# (Java 8 for <=1.16.5, 17 for 1.17-1.20.4, 21 for 1.20.5-1.21.x, 25 for 26.x).
FROM eclipse-temurin:8-jre  AS java8
FROM eclipse-temurin:17-jre AS java17
FROM eclipse-temurin:25-jre AS java25

FROM eclipse-temurin:21-jre
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 tini \
 && rm -rf /var/lib/apt/lists/*

COPY --from=java8  /opt/java/openjdk /opt/java/8
COPY --from=java17 /opt/java/openjdk /opt/java/17
COPY --from=java25 /opt/java/openjdk /opt/java/25
RUN ln -s /opt/java/openjdk /opt/java/21

COPY scripts/ /opt/mcctl/
RUN chmod +x /opt/mcctl/*.sh /opt/mcctl/mcctl.py \
 && ln -s /opt/mcctl/mcctl.py /usr/local/bin/mcctl

ENV DATA_DIR=/data \
    JAVA_ROOT=/opt/java \
    PERSIST_DIR=/persist \
    SERVER_PORT=25565 \
    EULA=false \
    MEMORY=2G \
    MC_VERSION=latest \
    LOADER=vanilla \
    LOADER_VERSION= \
    PUID=1000 \
    PGID=1000

WORKDIR /data
VOLUME /data
EXPOSE 25565

# Long start period: first start downloads and installs the server.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=3 \
  CMD python3 -c "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ['SERVER_PORT'])), 3)" || exit 1

ENTRYPOINT ["tini", "--", "/opt/mcctl/entrypoint.sh"]
