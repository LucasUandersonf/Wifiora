<?php

require_once __DIR__ . '/../../env.php';
loadEnv();

class UnifiService
{
    private $controllerUrl;
    private $username;
    private $password;
    private $site;
    private $minutes;
    private $cookieFile;

    public function __construct()
    {
        $this->controllerUrl = getenv('UNIFI_URL');
        $this->username = getenv('UNIFI_USERNAME');
        $this->password = getenv('UNIFI_PASSWORD');
        $this->site = getenv('UNIFI_SITE');
        $this->minutes = getenv('UNIFI_MINUTES') ?: 60;

        $this->cookieFile = tempnam(sys_get_temp_dir(), 'unifi_cookie');
    }

    public function login()
    {
        $ch = curl_init();

        curl_setopt($ch, CURLOPT_URL, "{$this->controllerUrl}/api/login");
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
            'username' => $this->username,
            'password' => $this->password
        ]));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_COOKIEJAR, $this->cookieFile);
        curl_setopt($ch, CURLOPT_COOKIEFILE, $this->cookieFile);
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);

        $response = curl_exec($ch);
        curl_close($ch);

        return json_decode($response, true);
    }

    public function authorize($mac)
    {
        return $this->request('cmd/stamgr', [
            'cmd' => 'authorize-guest',
            'mac' => $mac,
            'minutes' => intval($this->minutes) // esta carregando do .env
        ]);
    }

    private function request($endpoint, $data = [], $method = 'POST')
    {
        $ch = curl_init();
        $url = "{$this->controllerUrl}/api/s/{$this->site}/{$endpoint}";

        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_COOKIEJAR, $this->cookieFile);
        curl_setopt($ch, CURLOPT_COOKIEFILE, $this->cookieFile);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);

        if ($method === 'POST') {
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
        }

        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'Content-Type: application/json'
        ]);

        $response = curl_exec($ch);

        if (curl_errno($ch)) {
            throw new Exception('Erro CURL: ' . curl_error($ch));
        }

        curl_close($ch);
        return json_decode($response, true);
    }
}
