#!/bin/sh
# Inside the throwaway lab container: download official Minecraft server jars from Mojang piston-meta (sha1 checked
# against the version json) and run the built-in data generator (--reports --server).
#   fetch_and_generate.sh 1.21.11 26.3 ...      -> /srv/mc/<ver>/{server.jar,generated/,SHA1,JAVA}
set -eu
MANIFEST=https://piston-meta.mojang.com/mc/game/version_manifest_v2.json
mkdir -p /srv/mc
curl -fsS "$MANIFEST" -o /srv/mc/manifest.json
for ver in "$@"; do
  d=/srv/mc/$ver
  mkdir -p "$d"
  url=$(jq -r --arg v "$ver" '.versions[] | select(.id==$v) | .url' /srv/mc/manifest.json)
  [ -n "$url" ] || { echo "no version $ver"; exit 1; }
  curl -fsS "$url" -o "$d/version.json"
  jar_url=$(jq -r .downloads.server.url "$d/version.json")
  sha1=$(jq -r .downloads.server.sha1 "$d/version.json")
  java=$(jq -r .javaVersion.majorVersion "$d/version.json")
  if [ ! -f "$d/server.jar" ] || [ "$(sha1sum "$d/server.jar" | cut -d' ' -f1)" != "$sha1" ]; then
    curl -fsS "$jar_url" -o "$d/server.jar"
  fi
  got=$(sha1sum "$d/server.jar" | cut -d' ' -f1)
  [ "$got" = "$sha1" ] || { echo "sha1 mismatch for $ver: $got != $sha1"; exit 1; }
  echo "$sha1" > "$d/SHA1"; echo "$java" > "$d/JAVA"
  jdk=/usr/lib/jvm/java-$java-openjdk-amd64/bin/java
  [ -x "$jdk" ] || jdk=/usr/lib/jvm/java-25-openjdk-amd64/bin/java
  (cd "$d" && rm -rf generated && "$jdk" -Xmx2G -DbundlerMainClass=net.minecraft.data.Main -jar server.jar \
      --reports --server --output generated > gen.log 2>&1) || { tail -20 "$d/gen.log"; exit 1; }
  echo "$ver sha1=$sha1 java=$java reports: $(ls "$d/generated/reports" | tr '\n' ' ')"
done
# client jar (asset names for resource-pack checks) + sounds.json from the official asset index, sha1 checked
for ver in "$@"; do
  d=/srv/mc/$ver
  csha=$(jq -r .downloads.client.sha1 "$d/version.json")
  if [ ! -f "$d/client.jar" ] || [ "$(sha1sum "$d/client.jar" | cut -d' ' -f1)" != "$csha" ]; then
    curl -fsS "$(jq -r .downloads.client.url "$d/version.json")" -o "$d/client.jar"
  fi
  [ "$(sha1sum "$d/client.jar" | cut -d' ' -f1)" = "$csha" ] || { echo "client sha1 mismatch $ver"; exit 1; }
  curl -fsS "$(jq -r .assetIndex.url "$d/version.json")" -o "$d/assets.json"
  h=$(jq -r '.objects["minecraft/sounds.json"].hash' "$d/assets.json")
  curl -fsS "https://resources.download.minecraft.net/$(echo "$h" | cut -c1-2)/$h" -o "$d/sounds.json"
  [ "$(sha1sum "$d/sounds.json" | cut -d' ' -f1)" = "$h" ] || { echo "sounds.json sha1 mismatch $ver"; exit 1; }
  echo "$ver client sha1=$csha sounds.json ok"
done
