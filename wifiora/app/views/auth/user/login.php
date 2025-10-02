<!DOCTYPE html>
<html lang="pt-BR">

<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>wifiora - Login</title>


  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />

  <style>
    body,
    html {
      height: 100%;
      margin: 0;
      font-family: Arial, sans-serif;
      background-image: url(https://satahealth.com/wp-content/uploads/2023/12/041.jpg);
      background-size: cover;
      background-position: center;
      background-repeat: no-repeat;
      display: flex;
      justify-content: center;
      align-items: center;
      position: relative;
      overflow: hidden;
    }



    .background-overlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background-color: rgba(0, 0, 0, 0.55);
      z-index: 0;
    }

    .login-container {
      position: relative;
      z-index: 1;
      background-color: rgba(255, 255, 255, 0.9);
      padding: 3rem 2.5rem;
      border-radius: 1rem;
      box-shadow: 0 0 25px rgba(0, 0, 0, 0.25);
      max-width: 380px;
      width: 90%;
      text-align: center;
    }


    .login-container .form-control {
      border-radius: 0.5rem;
      padding: 0.75rem 1rem;
      font-size: 1.1rem;
    }


    .btn-login {
      background-color: #ff6600;
      border: none;
      font-weight: 600;
      padding: 0.75rem;
      font-size: 1.1rem;
      border-radius: 0.6rem;
      transition: background-color 0.3s ease;
      width: 100%;
    }

    .btn-login:hover {
      background-color: #cc5200;
    }


    .register-link {
      margin-top: 1.25rem;
      font-size: 0.95rem;
    }

    .register-link a {
      color: #ff6600;
      text-decoration: none;
      font-weight: 600;
    }

    .register-link a:hover {
      text-decoration: underline;
    }
  </style>
</head>

<body>
  <div class="background-overlay"></div>

  <div class="login-container shadow-lg">
    <h2 class="mb-4 fw-bold">Entrar</h2>
    <form method="POST" action="" class="d-flex flex-column align-items-center">
      <div class="mb-3 w-100">
        <label for="email" class="form-label text-start d-block fw-semibold">Email:</label>
        <input type="email" name="email" id="email" class="form-control" required placeholder="Digite seu email" />
      </div>
      <div class="mb-4 w-100">
        <label for="password" class="form-label text-start d-block fw-semibold">Senha:</label>
        <input type="password" name="password" id="password" class="form-control" required
          placeholder="Digite sua senha" />
      </div>
      <button type="submit" class="btn btn-login">Entrar</button>
    </form>
    <p class="register-link">Não tem conta? <a href="/register_user.php">Cadastre-se</a></p>
  </div>


  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>

</html>