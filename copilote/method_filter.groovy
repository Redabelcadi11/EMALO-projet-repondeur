args.eachWithIndex { value, index ->
    if (index == 0) return
}

def className = args[0]
def patterns = args.length > 1 ? args[1..-1].collect { it.toLowerCase() } : []
def c = Class.forName(className)
println("### ${c.name}")
def classes = []
for (def k = c; k != null; k = k.superclass) {
    classes.add(k)
}
classes.each { klass ->
    println("-- methods ${klass.name}")
    klass.declaredMethods
    .findAll { m ->
        def s = m.toGenericString().toLowerCase()
        patterns.isEmpty() || patterns.any { s.contains(it) }
    }
    .sort { it.name }
    .each { m ->
        m.accessible = true
        println(m.toGenericString())
    }
    println("-- fields ${klass.name}")
    klass.declaredFields
    .findAll { f ->
        def s = f.toGenericString().toLowerCase()
        patterns.isEmpty() || patterns.any { s.contains(it) }
    }
    .each { f ->
        f.accessible = true
        println(f.toGenericString())
    }
}
