<!DOCTYPE html>
<html lang="pt-BR">

<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cadastro - wifiora</title>

  <!-- Google Fonts -->
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">

  <!-- Bootstrap CSS -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />

  <style>
    body {
      margin: 0;
      padding: 0;
      font-family: 'Inter', sans-serif;
      background-image: linear-gradient(to bottom right, rgba(0, 0, 0, 0.7), rgba(30, 30, 30, 0.7)),
        url('https://satahealth.com/wp-content/uploads/2023/12/041.jpg');
      background-size: cover;
      background-position: center;
      background-repeat: no-repeat;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
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

    .form-container {
      background-color: #ffffffee;
      padding: 3rem 2.5rem;
      border-radius: 1rem;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
      width: 100%;
      max-width: 500px;
    }

    .form-container h2 {
      font-weight: 700;
      margin-bottom: 2rem;
      text-align: center;
    }

    .form-label {
      font-weight: 600;
    }

    .form-control,
    .form-select {
      border-radius: 0.6rem;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      border: 1px solid #ccc;
      transition: border-color 0.3s ease;
    }

    .form-control:focus,
    .form-select:focus {
      border-color: #ff6600;
      box-shadow: 0 0 0 0.2rem rgba(255, 102, 0, 0.25);
    }

    .btn-register {
      background-color: #ff6600;
      color: #fff;
      font-weight: 600;
      padding: 0.75rem;
      border: none;
      border-radius: 0.6rem;
      width: 100%;
      transition: background-color 0.3s ease;
    }

    .btn-register:hover {
      background-color: #e65c00;
    }
  </style>
</head>

<body>
  <div class="form-container">
    <h2>Cadastrar Usuário</h2>
    <form action="register.php" method="post" class="row g-3">
      <div class="col-12">
        <label for="name" class="form-label">Nome</label>
        <input type="text" name="name" id="name" class="form-control" placeholder="Digite seu nome" required>
      </div>

      <div class="col-12">
        <label for="email" class="form-label">Email</label>
        <input type="email" name="email" id="email" class="form-control" placeholder="Digite seu email" required>
      </div>

      <div class="col-12">
        <label for="cpf" class="form-label">CPF</label>
        <input type="text" name="cpf" id="cpf" class="form-control" placeholder="Digite seu CPF" required>
      </div>

      <div class="col-12">
        <label for="user_type" class="form-label">Tipo de Usuário</label>
        <select name="user_type" id="user_type" class="form-select" required>
          <option value="">Selecione</option>
          <option value="funcionario">Funcionário</option>
          <option value="paciente">Paciente</option>
          <option value="acompanhante">Acompanhante</option>
        </select>
      </div>

      <div class="col-12">
        <label for="birth_date" class="form-label">Data de Nascimento</label>
        <input type="date" name="birth_date" id="birth_date" class="form-control" required>
      </div>

      <div class="col-12">
        <label for="password" class="form-label">Senha</label>
        <input type="password" name="password" id="password" class="form-control" placeholder="Digite sua senha" required>
      </div>

      <div class="col-12">
        <button type="submit" class="btn btn-register">Cadastrar</button>
      </div>
    </form>
    <p class="register-link">Já tem conta? <a href="/login_user.php">Entrar</a></p>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>

</html>
