// compile classpath for Paper plugins (Paper API 1.21.11); `gradle cpOut` copies it to /opt/mcp/cp/paper
plugins { java }
repositories { mavenCentral(); maven("https://repo.papermc.io/repository/maven-public/") }
dependencies { compileOnly("io.papermc.paper:paper-api:1.21.11-R0.1-SNAPSHOT") }
tasks.register<Copy>("cpOut") { from(configurations.compileClasspath); into("/opt/mcp/cp/paper") }
val jd by configurations.creating { isTransitive = false }
dependencies { jd("io.papermc.paper:paper-api:1.21.11-R0.1-SNAPSHOT:javadoc") }
tasks.register<Copy>("javadocOut") { from(jd); into("/opt/mcp/javadoc/paper") }
