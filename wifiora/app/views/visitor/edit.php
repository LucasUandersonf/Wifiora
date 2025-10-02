<?php require __DIR__ . '/../partials/header.php'; ?>

<div class="container">
    <h2>Editar Visitante</h2>
    <?php if(isset($error_message)) echo "<p class='error'>$error_message</p>"; ?>
    <form method="POST" action="">
        <input type="hidden" name="id" value="<?= htmlspecialchars($visitor['id']) ?>">

        <div class="input-group">
            <label>Email:</label>
            <input type="email" name="email" value="<?= htmlspecialchars($visitor['email']) ?>" required>
        </div>
        <div class="input-group">
            <label>Nova Senha (opcional):</label>
            <input type="password" name="password">
        </div>
        <button type="submit" class="btn">Atualizar</button>
        <a href="/public/visitantes.php" class="btn">Cancelar</a>
    </form>
</div>

<?php require __DIR__ . '/../partials/footer.php'; ?>