pipelineJob('quantroute') {
    description('QuantRoute production-foundation Jenkins pipeline')

    properties {
        disableConcurrentBuilds {
            abortPrevious(true)
        }
        buildDiscarder {
            strategy {
                logRotator {
                    numToKeepStr('20')
                    artifactNumToKeepStr('20')
                }
            }
        }
    }

    definition {
        cpsScm {
            scm {
                git {
                    remote {
                        url('https://github.com/Krishnauprit18/Quantum-Inspired-Intelligent-Traffic-Route-Optimization-in-Transportation-Systems.git')
                    }
                    branches('*/production-foundation')
                }
            }
            scriptPath('Jenkinsfile')
            lightweight(true)
        }
    }
}
