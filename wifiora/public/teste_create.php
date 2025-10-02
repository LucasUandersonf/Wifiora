<?php
// ATENÇÃO: Arquivo para TESTES LOCAIS. Remova ou proteja depois de usar!
// Acesso público: permite criar administradores sem login.
// NÃO DEIXE ISSO EM PRODUÇÃO.

/*
  Estrutura esperada:
  /config/config.php  -> classe Database (conexão)
  /public/create_admin.php  -> este arquivo
  /public/login.php   -> página de login (link após criação)
*/

require_once __DIR__ . '/../config/config.php';

// Instanciar conexão
$db = new Database();
$conn = $db->conn;

$error = '';
$success = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // Receber e sanitizar entrada
    $email = filter_var(trim($_POST['email'] ?? ''), FILTER_VALIDATE_EMAIL);
    $password = trim($_POST['password'] ?? '');

    if (!$email) {
        $error = 'Informe um e-mail válido.';
    } elseif (strlen($password) < 6) {
        $error = 'A senha deve ter pelo menos 6 caracteres.';
    } else {
        // Verificar se já existe admin com esse e-mail
        $stmt = $conn->prepare("SELECT id FROM admins WHERE email = ?");
        $stmt->bind_param("s", $email);
        $stmt->execute();
        $stmt->store_result();

        if ($stmt->num_rows > 0) {
            $error = 'Já existe um administrador com esse e-mail.';
            $stmt->close();
        } else {
            $stmt->close();
            // Inserir novo admin
            $hashed = password_hash($password, PASSWORD_DEFAULT);
            $insert = $conn->prepare("INSERT INTO admins (email, password) VALUES (?, ?)");
            $insert->bind_param("ss", $email, $hashed);
            if ($insert->execute()) {
                $success = 'Administrador criado com sucesso.';
                // Opcional: limpar variáveis para evitar reenvio
                $email = '';
                $password = '';
            } else {
                $error = 'Erro ao criar administrador: ' . $insert->error;
            }
            $insert->close();
        }
    }
}
?>
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Criar Administrador (Teste)</title>
    <link rel="stylesheet" href="css/styles.css">
    <style>
        /* Pequeno estilo local para visual decente */
        body { font-family: Arial, sans-serif; background:#f4f6f8; margin:0; padding:20px; }
        .box { max-width:520px; margin:40px auto; background:#fff; padding:24px; border-radius:8px; box-shadow:0 6px 20px rgba(0,0,0,0.06);}
        h1{margin:0 0 12px}
        .note { background:#fff3cd; border:1px solid #ffeeba; padding:10px; border-radius:6px; margin-bottom:14px; color:#856404;}
        .error { background:#f8d7da; border:1px solid #f5c6cb; color:#721c24; padding:10px; border-radius:6px; margin-bottom:14px; }
        .success { background:#d4edda; border:1px solid #c3e6cb; color:#155724; padding:10px; border-radius:6px; margin-bottom:14px; }
        .input-group { margin-bottom:12px; }
        label{display:block;margin-bottom:6px;font-weight:600}
        input[type="email"], input[type="password"]{width:100%;padding:10px;border:1px solid #dfe6ee;border-radius:6px}
        .btn { display:inline-block; padding:10px 14px; background:#2d6cdf; color:#fff; text-decoration:none; border-radius:6px; border:none; cursor:pointer; }
        .btn-link { background:transparent;color:#2d6cdf; border:0; cursor:pointer; padding:0; text-decoration:underline; }
        .small { font-size:13px; color:#666; margin-top:8px; }
    </style>
</head>
<body>
    <div class="box">
        <h1>Criar Administrador (TESTE)</h1>

        <div class="note">
            <strong>AVISO:</strong> Esta página permite criar administradores sem autenticação. Use apenas para testes locais. <br>
            Após finalizar os testes, <strong>exclua</strong> ou proteja este arquivo (por exemplo, remova-o ou adicione verificação de sessão).
        </div>

        <?php if ($error): ?>
            <div class="error"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>

        <?php if ($success): ?>
            <div class="success"><?= htmlspecialchars($success) ?></div>
        <?php endif; ?>

        <form method="POST" action="">
            <div class="input-group">
                <label for="email">Email</label>
                <input id="email" type="email" name="email" required value="<?= isset($email) ? htmlspecialchars($email) : '' ?>">
            </div>

            <div class="input-group">
                <label for="password">Senha</label>
                <input id="password" type="password" name="password" required>
                <div class="small">Mínimo 6 caracteres. Depois de criar o admin, faça login em <a href="login.php">Login</a>.</div>
            </div>

            <button type="submit" class="btn">Criar Administrador</button>
            &nbsp;
            <a href="login.php" class="btn-link">Ir para Login</a>
        </form>
    </div>
</body>
</html>