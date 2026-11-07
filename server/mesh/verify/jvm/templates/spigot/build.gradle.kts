// compile classpath for Spigot/Bukkit-only plugins (Spigot API 1.21.11, official SpigotMC repo)
plugins { java }
repositories { mavenCentral(); maven("https://hub.spigotmc.org/nexus/content/repositories/snapshots/") }
dependencies { compileOnly("org.spigotmc:spigot-api:1.21.11-R0.1-SNAPSHOT") }
tasks.register<Copy>("cpOut") { from(configurations.compileClasspath); into("/opt/mcp/cp/spigot") }
val jd by configurations.creating { isTransitive = false }
dependencies { jd("org.spigotmc:spigot-api:1.21.11-R0.1-SNAPSHOT:javadoc") }
tasks.register<Copy>("javadocOut") { from(jd); into("/opt/mcp/javadoc/spigot") }
