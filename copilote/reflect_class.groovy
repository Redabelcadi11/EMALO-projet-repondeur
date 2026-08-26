args.each { name ->
    println("### ${name}")
    def c = Class.forName(name)
    println("class ${c.name} extends ${c.superclass?.name}")
    println("-- constructors")
    c.declaredConstructors.each { it.accessible = true; println(it.toGenericString()) }
    println("-- methods")
    c.declaredMethods.sort { it.name }.each { m ->
        m.accessible = true
        println(m.toGenericString())
    }
    println("-- fields")
    c.declaredFields.each { f ->
        f.accessible = true
        println(f.toGenericString())
    }
}
