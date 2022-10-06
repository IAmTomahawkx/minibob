create table reminders
(
    guild_id    bigint,
    channel_id  bigint,
    message     text,
    remind_time timestamp,
    msg_link    text,
    user_id     bigint
);
create table default_rtfm
(
    guild_id bigint primary key,
    name     text
);
CREATE TABLE pages
(
    quick text,
    long  text,
    url   text
);