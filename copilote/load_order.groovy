import fr.infologic.core.communication.RemoteServiceFactoryImpl
import fr.infologic.ventes.services.commande.CommandeService

fr.infologic.hibernate.proxy.BytecodeProviderImpl.setup()

def cookie = args[0]
def number = args[1]

def factory = new RemoteServiceFactoryImpl()
factory.setUrl(new URL("http://172.16.213.101:8080/ventes/ProxyServlet"))
factory.setCompression(1)
factory.setThreadRequestProperty("X-Prop-LongServiceCall", "1")
factory.setThreadRequestProperty("X-Prop-SaisieId", "")
factory.initialize()

def injectCookie = {
    def httpClientField = factory.getClass().getDeclaredField("httpClient")
    httpClientField.accessible = true
    def httpClient = httpClientField.get(factory)
    def cookieManagerField = httpClient.getClass().getDeclaredField("cookieManager")
    cookieManagerField.accessible = true
    def cookieManager = cookieManagerField.get(httpClient)
    def httpCookie = new java.net.HttpCookie("JSESSIONID", cookie.replace("JSESSIONID=", ""))
    httpCookie.path = "/ventes"
    cookieManager.cookieStore.add(new URI("http://172.16.213.101:8080/ventes"), httpCookie)
}

def fmt = { v -> v == null ? "" : v.toString() }
def ik = { v -> v == null ? "" : v.getIk() }

try {
    injectCookie()
    factory.setThreadRequestProperty("X-Prop-ServiceSource", "debug load order")
    def dto = ((CommandeService) factory.getService(CommandeService.ROLE)).loadNumCde(number, true)
    def c = dto.getCommande()
    println("numCde=${fmt(c.getNumCde())}")
    println("datCde=${fmt(c.getDatCde())}")
    println("datLiv=${fmt(c.getDatLiv())}")
    println("datDepart=${fmt(c.getDatDepart())}")
    println("cliLivCode=${fmt(c.getCliLiv()?.getCode())}")
    println("cliLivIk=${ik(c.getCliLiv())}")
    println("transp=${fmt(c.getTransp()?.getCode())}")
    println("etatCde=${fmt(c.getEtatCde())}")
    println("statutCde=${fmt(c.getStatutCde())}")
} finally {
    factory.dispose()
}
