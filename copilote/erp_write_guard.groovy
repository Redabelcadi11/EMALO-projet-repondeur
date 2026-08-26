import groovy.json.JsonSlurper


void assertErpWriteAllowed(File projectRoot, String operation) {
    def policyFile = new File(projectRoot, 'config/erp-safety.json')
    if (!policyFile.isFile()) {
        throw new SecurityException("[ERP_WRITE_BLOCKED] ${operation}: politique absente ${policyFile}")
    }

    def policy
    try {
        policy = new JsonSlurper().parse(policyFile)
    } catch (Throwable error) {
        throw new SecurityException("[ERP_WRITE_BLOCKED] ${operation}: politique illisible ${policyFile}: ${error.message}")
    }

    def mode = String.valueOf(policy.mode ?: 'evaluation').trim().toLowerCase()
    def forcedMode = String.valueOf(System.getenv('REPONDEUR_ERP_MODE') ?: '').trim().toLowerCase()
    def reasons = []
    if (policy.evaluation_lock != false) reasons.add("verrou d'evaluation actif")
    if (mode != 'production') reasons.add("mode=${mode}")
    if (forcedMode && forcedMode != 'production') reasons.add("REPONDEUR_ERP_MODE=${forcedMode}")
    if (policy.allow_erp_writes != true) reasons.add("allow_erp_writes n'est pas true")

    def confirmationEnv = String.valueOf(policy.write_confirmation_env ?: 'REPONDEUR_ERP_WRITE_CONFIRMATION').trim()
    def confirmationValue = String.valueOf(policy.write_confirmation_value ?: '').trim()
    def confirmationOk = confirmationEnv && confirmationValue && System.getenv(confirmationEnv) == confirmationValue
    if (!confirmationOk) reasons.add('confirmation de production absente')

    if (reasons) {
        throw new SecurityException(
            "[ERP_WRITE_BLOCKED] ${operation} vers Copilote ERP: ${reasons.join('; ')} (politique=${policyFile})"
        )
    }
}

