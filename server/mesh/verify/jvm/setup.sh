#!/usr/bin/env bash
# Build harness for Minecraft plugin/mod answers, run INSIDE the throwaway mc-plugins LXD container (Ubuntu 24.04,
# starnat0 only). Idempotent. Official sources only; every download is checked against the publisher's checksum.
#   lxc exec mc-plugins -- bash /opt/mcp/setup.sh [all|servers|cp|svc]
set -euo pipefail
M=/opt/mcp
step=${1:-all}
J21=/usr/lib/jvm/java-21-openjdk-amd64
J25=/usr/lib/jvm/java-25-openjdk-amd64          # Fabric Loom 1.19 needs Gradle on Java 25 (mods still target 21)
mkdir -p $M/dl $M/servers $M/work $M/index

fetch() {  # url dest sha256
  [ -f "$2" ] && echo "$3  $2" | sha256sum -c --quiet && return 0
  curl -fsSL -o "$2.part" "$1" && echo "$3  $2.part" | sha256sum -c --quiet && mv "$2.part" "$2"
}

if [ "$step" = all ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq openjdk-21-jdk-headless openjdk-25-jdk-headless unzip jq python3 >/dev/null
  update-alternatives --set java $J21/bin/java
  # Gradle 9.8.2 (services.gradle.org publishes the sha256 next to the zip)
  if [ ! -x $M/gradle-9.8.2/bin/gradle ]; then
    fetch https://services.gradle.org/distributions/gradle-9.8.2-bin.zip $M/dl/gradle-9.8.2-bin.zip \
      "$(curl -fsSL https://services.gradle.org/distributions/gradle-9.8.2-bin.zip.sha256)"
    unzip -q -o $M/dl/gradle-9.8.2-bin.zip -d $M && ln -sf $M/gradle-9.8.2/bin/gradle /usr/local/bin/gradle
  fi
  id mcp >/dev/null 2>&1 || useradd -r -m -d $M/home mcp
fi

if [ "$step" = all ] || [ "$step" = servers ]; then
  # Paper 1.21.11 build 132 and Velocity 3.5.1 build 615 (fill.papermc.io v3 API checksums)
  mkdir -p $M/servers/paper $M/servers/velocity $M/servers/fabric $M/servers/neoforge
  fetch https://fill-data.papermc.io/v1/objects/5ffef465eeeb5f2a3c23a24419d97c51afd7dbb4923ff42df9a3f58bba1ccfba/paper-1.21.11-132.jar \
    $M/servers/paper/paper.jar 5ffef465eeeb5f2a3c23a24419d97c51afd7dbb4923ff42df9a3f58bba1ccfba
  fetch https://fill-data.papermc.io/v1/objects/b4e3164df5377346854dc6cb9e6a78022b1946ff69e89676313f5f6f1c6f0fb3/velocity-3.5.1-615.jar \
    $M/servers/velocity/velocity.jar b4e3164df5377346854dc6cb9e6a78022b1946ff69e89676313f5f6f1c6f0fb3
  # Fabric server launcher (meta.fabricmc.net, loader 0.20.1, installer 1.1.2; no published checksum: recorded here
  # after the first download) + Fabric API 0.141.6 (maven.fabricmc.net .sha256)
  [ -f $M/servers/fabric/fabric-server.jar ] || curl -fsSL -o $M/servers/fabric/fabric-server.jar \
    https://meta.fabricmc.net/v2/versions/loader/1.21.11/0.20.1/1.1.2/server/jar
  sha256sum $M/servers/fabric/fabric-server.jar > $M/servers/fabric/fabric-server.jar.sha256
  mkdir -p $M/servers/fabric/base-mods
  fetch "https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/0.141.6+1.21.11/fabric-api-0.141.6+1.21.11.jar" \
    $M/servers/fabric/base-mods/fabric-api.jar bdff7fd7e220085cfad2ff9b1f40dde6534ae0b96cf378f97a374bc54cb9ed0f
  # NeoForge 21.11.48 installer (maven.neoforged.net .sha256)
  fetch https://maven.neoforged.net/releases/net/neoforged/neoforge/21.11.48/neoforge-21.11.48-installer.jar \
    $M/dl/neoforge-installer.jar 1f14a4bac4aa885a497550fa5a8374451b7014cec27e1bb69ab16742fb689db0
  [ -d $M/servers/neoforge/libraries ] || (cd $M/servers/neoforge && $J21/bin/java -jar $M/dl/neoforge-installer.jar --installServer . >install.log 2>&1)
  for s in paper fabric neoforge; do
    # Mojang's EULA: only the owner may accept it (then he writes eula=true himself); load tests skip these until then
    [ -f $M/servers/$s/eula.txt ] || echo "eula=false" > $M/servers/$s/eula.txt
    cat > $M/servers/$s/server.properties <<'EOF'
online-mode=false
level-type=minecraft\:flat
generate-structures=false
spawn-protection=0
view-distance=2
simulation-distance=2
server-ip=127.0.0.1
server-port=25565
enable-query=false
enable-rcon=false
max-players=2
EOF
  done
  chown -R mcp $M/servers
fi

if [ "$step" = all ] || [ "$step" = cp ]; then
  # compile classpaths (templates/*/build.gradle*: Paper API, Spigot API, Velocity API, Fabric Loom yarn + mojmap,
  # NeoForge ModDevGradle) and the javadoc jars for the deprecation notes
  for d in paper spigot velocity; do (cd $M/templates/$d && gradle -q --console=plain cpOut javadocOut); done
  for d in fabric fabric-mojmap neoforge; do (cd $M/templates/$d && JAVA_HOME=$J25 gradle -q --console=plain cpOut); done
  python3 $M/build_index.py $M/javadoc $M/index/deprecations.json
fi

if [ "$step" = all ] || [ "$step" = svc ]; then
  mkdir -p $M/svc && cp "$(ls $M/cp/paper/gson-*.jar | head -1)" $M/svc/gson.jar
  $J21/bin/javac -cp $M/svc/gson.jar -d $M/svc/classes $M/svc/CompileServer.java
  [ -f $M/token ] || (head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > $M/token)
  chmod 600 $M/token && chown mcp $M/token $M/work && chown -R mcp $M/svc
  cp $M/svc/mc-compile.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now mc-compile
  systemctl restart mc-compile
fi
echo "setup $step done"
