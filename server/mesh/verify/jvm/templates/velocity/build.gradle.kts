// compile classpath + annotation processor for Velocity proxy plugins (Velocity API 3.5.1)
plugins { java }
repositories { mavenCentral(); maven("https://repo.papermc.io/repository/maven-public/") }
dependencies { compileOnly("com.velocitypowered:velocity-api:3.5.1"); annotationProcessor("com.velocitypowered:velocity-api:3.5.1") }
tasks.register<Copy>("cpOut") { from(configurations.compileClasspath); into("/opt/mcp/cp/velocity") }
val jd by configurations.creating { isTransitive = false }
dependencies { jd("com.velocitypowered:velocity-api:3.5.1:javadoc") }
tasks.register<Copy>("javadocOut") { from(jd); into("/opt/mcp/javadoc/velocity") }
