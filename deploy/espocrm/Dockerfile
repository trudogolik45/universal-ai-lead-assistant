# EspoCRM с модулем Uala (custom/Espo/Modules/Uala): свои сущности и поля лежат в образе,
# а не в томе, поэтому их версия всегда та, что в репо. В базу их переносит
# `bin/command rebuild` (make deploy; при первой установке — сам entrypoint).
ARG ESPOCRM_VERSION=10.0.10
FROM espocrm/espocrm:${ESPOCRM_VERSION}-apache

COPY --chown=www-data:www-data custom/ /var/www/html/custom/
