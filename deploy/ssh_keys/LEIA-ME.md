# Chaves SSH públicas autorizadas no servidor

Coloca aqui chaves **públicas** (ficheiros `.pub`, uma por pessoa/computador). Uma chave pública não é
secreta. **Nunca** coloques aqui a chave privada (o ficheiro sem `.pub`).

Para as ativar, o root corre à mão no servidor: `bash /opt/carretos/deploy/autorizar_ssh.sh`
(o script não corre sozinho em nenhuma atualização).
